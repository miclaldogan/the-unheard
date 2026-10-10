"""M2 endpoints: model status, predictions, labels, annotations, memory, ECHO-0 lines."""

from __future__ import annotations

from typing import Any

import numpy as np
from fastapi import APIRouter, Depends, Query

from unheard.api.deps import Services, get_services, require_token, valid_recording_id
from unheard.api.schemas_m2 import (
    AnnotationIn,
    AnnotationOut,
    AnnotationResult,
    EchoLine,
    LabelIn,
    LabelOut,
    MemoryOverview,
    ModelStatusOut,
    NeighbourOut,
    PredictionOut,
)
from unheard.errors import NotFound, NotReady, ValidationFailed
from unheard.memory.service import AnnotationRequest
from unheard.storage.repos import EventRepo, JobRepo, RecordingRepo
from unheard.storage.repos_m2 import (
    AnnotationRepo,
    AnnotationRow,
    EmbeddingRepo,
    LabelRepo,
    ModelVersionRepo,
    PredictionRepo,
)

router = APIRouter(dependencies=[Depends(require_token)])


# ----------------------------------------------------------------------------------- model


@router.get("/model", response_model=ModelStatusOut)
def model_status(services: Services = Depends(get_services)) -> ModelStatusOut:
    st = services.models.status()
    with services.db.connection() as conn:
        versions = ModelVersionRepo.list(conn)
    return ModelStatusOut(
        status=st.status,
        model_id=st.model_id,
        revision=st.revision,
        device=st.device,
        embedding_dim=st.embedding_dim,
        preprocessing_version=st.preprocessing_version,
        load_seconds=st.load_seconds,
        error=st.error,
        inference="local",
        known_versions=[
            {
                "id": v.id,
                "name": v.name,
                "revision": v.revision,
                "preprocessing_version": v.preprocessing_version,
            }
            for v in versions
        ],
    )


@router.post("/model/load", response_model=ModelStatusOut)
def model_load(services: Services = Depends(get_services)) -> ModelStatusOut:
    if not services.models.enabled:
        raise NotReady("audio model is disabled (UNHEARD_MODEL=none)")
    try:
        services.models.get()
    except Exception as e:  # noqa: BLE001
        raise NotReady(f"model failed to load: {type(e).__name__}") from e
    return model_status(services)


# ------------------------------------------------------------------------------ predictions


def _active_model_version_id(services: Services, recording_id: str) -> str | None:
    with services.db.connection() as conn:
        base = PredictionRepo.latest(conn, recording_id, "base")
    return base.model_version_id if base else None


def _with_memory(results: list[dict[str, Any]], n: int = 10) -> list[dict[str, Any]]:
    """Top-n candidates plus every candidate that carries personal-memory evidence."""
    out = list(results[:n])
    seen = {c["label_id"] for c in out}
    out += [
        c
        for c in results[n:]
        if c.get("memory_similarity") is not None and c["label_id"] not in seen
    ]
    return out


def _annotation_out(a: AnnotationRow, names: dict[str, tuple[str, str]]) -> AnnotationOut:
    return AnnotationOut(
        id=a.id,
        recording_id=a.recording_id,
        action=a.action,  # type: ignore[arg-type]
        status=a.status,  # type: ignore[arg-type]
        labels=[
            {
                "label_id": lid,
                "slug": names.get(lid, ("?", "?"))[0],
                "name": names.get(lid, ("?", lid))[1],
            }
            for lid in a.label_ids
        ],
        rejected_label_ids=a.rejected_label_ids,
        is_unknown=a.is_unknown,
        descriptors=a.descriptors,
        environment=a.environment,
        mood=a.mood,
        note=a.note,
        prediction_id=a.prediction_id,
        superseded_by=a.superseded_by,
        created_at=a.created_at,
    )


@router.get("/recordings/{recording_id}/prediction", response_model=PredictionOut)
def get_prediction(
    recording_id: str = Depends(valid_recording_id), services: Services = Depends(get_services)
) -> PredictionOut:
    with services.db.connection() as conn:
        rec = RecordingRepo.get(conn, recording_id)
        if rec is None:
            raise NotFound("recording not found")
        base = PredictionRepo.latest(conn, recording_id, "base")
        fused = PredictionRepo.latest(conn, recording_id, "fused")
        jobs = [j for j in JobRepo.for_recording(conn, recording_id) if j.stage == "infer"]
        ann = AnnotationRepo.active(conn, recording_id)
        names = services.memory.label_names(conn)
        mv = ModelVersionRepo.get(conn, base.model_version_id) if base else None
    st = services.models.status()
    job = jobs[0] if jobs else None
    if base is None:
        if job and job.status in ("queued", "running"):
            state = "analyzing"
        elif job and job.status == "failed":
            state = "inference_failed"
        elif st.status == "disabled":
            state = "model_disabled"
        else:
            state = "not_run"
    else:
        state = "remembered" if ann else "awaiting_feedback"
    return PredictionOut(
        recording_id=recording_id,
        state=state,  # type: ignore[arg-type]
        model_status=st.status,
        model={
            "id": mv.name,
            "revision": mv.revision,
            "preprocessing_version": mv.preprocessing_version,
            "embedding_dim": mv.embedding_dim,
        }
        if mv
        else None,
        job={
            "status": job.status,
            "error": job.error,
            "attempts": job.attempts,
            "updated_at": job.updated_at,
        }
        if job
        else None,
        base=None
        if base is None
        else {
            "score_kind": base.score_kind,
            "candidates": base.results[:10],
            "windows": base.windows or [],
            "inference_ms": base.inference_ms,
            "created_at": base.created_at,
        },
        fused=None
        if fused is None
        else {
            "score_kind": fused.score_kind,
            "memory_version": fused.memory_version,
            "candidates": _with_memory(fused.results),
            "novelty": fused.novelty,
            "created_at": fused.created_at,
        },
        annotation=_annotation_out(ann, names) if ann else None,
    )


@router.post("/recordings/{recording_id}/infer", status_code=202)
def request_inference(
    recording_id: str = Depends(valid_recording_id), services: Services = Depends(get_services)
) -> dict[str, str]:
    if not services.models.enabled:
        raise NotReady("audio model is disabled (UNHEARD_MODEL=none)")
    with services.db.transaction() as conn:
        rec = RecordingRepo.get(conn, recording_id)
        if rec is None:
            raise NotFound("recording not found")
        if rec.status != "ready":
            raise NotReady("features must be ready before inference", extra={"status": rec.status})
        if JobRepo.has_active(conn, recording_id, "infer"):
            raise NotReady("inference already queued or running")
        JobRepo.enqueue(conn, recording_id, "infer")
    return {"recording_id": recording_id, "state": "analyzing"}


@router.get("/recordings/{recording_id}/neighbours", response_model=list[NeighbourOut])
def get_neighbours(
    limit: int = Query(default=5, ge=1, le=50),
    recording_id: str = Depends(valid_recording_id),
    services: Services = Depends(get_services),
) -> list[NeighbourOut]:
    mvid = _active_model_version_id(services, recording_id)
    if mvid is None:
        return []
    with services.db.connection() as conn:
        me = EmbeddingRepo.pooled(conn, recording_id, mvid)
        if me is None:
            return []
        others = [e for e in EmbeddingRepo.all_pooled(conn, mvid) if e.recording_id != recording_id]
        names = services.memory.label_names(conn)
        anns = {a.recording_id: a for a in AnnotationRepo.active_for_all(conn)}
        recs = {r.id: r for r in RecordingRepo.list(conn, limit=5000, offset=0)}
    if not others:
        return []
    sims = np.stack([e.vec for e in others]) @ me.vec
    order = np.argsort(-sims)[:limit]
    out = []
    for i in order:
        e = others[i]
        a = anns.get(e.recording_id)
        r = recs.get(e.recording_id)
        out.append(
            NeighbourOut(
                recording_id=e.recording_id,
                similarity=round(float(sims[i]), 4),
                labels=[names[lid][1] for lid in a.label_ids] if a else [],
                is_unknown=bool(a and a.is_unknown),
                captured_at=(r.captured_at or r.created_at) if r else None,
                duration_s=r.duration_s if r else None,
            )
        )
    return out


# ----------------------------------------------------------------------------------- labels


@router.get("/labels", response_model=list[LabelOut])
def list_labels(
    q: str | None = Query(default=None, max_length=64), services: Services = Depends(get_services)
) -> list[LabelOut]:
    from unheard.storage.repos_m2 import ExemplarRepo

    with services.db.connection() as conn:
        services.memory.ensure_vocabulary(conn)
        labs = LabelRepo.list(conn, q)
        counts: dict[str, int] = {}
        for mv in ModelVersionRepo.list(conn):
            for k, v in ExemplarRepo.counts_by_label(conn, mv.id).items():
                counts[k] = counts.get(k, 0) + v
    return [
        LabelOut(
            id=lab.id,
            slug=lab.slug,
            name=lab.name,
            origin=lab.origin,  # type: ignore[arg-type]
            n_exemplars=counts.get(lab.id, 0),
            hue_seed=lab.hue_seed,
        )
        for lab in labs
    ]


@router.post("/labels", response_model=LabelOut, status_code=201)
def create_label(body: LabelIn, services: Services = Depends(get_services)) -> LabelOut:
    try:
        with services.db.transaction() as conn:
            lab, created = services.memory.create_label(conn, body.name)
    except ValueError as e:
        raise ValidationFailed(str(e)) from e
    _embed_label_text(services, lab.id)
    return LabelOut(
        id=lab.id,
        slug=lab.slug,
        name=lab.name,
        origin=lab.origin,  # type: ignore[arg-type]
        n_exemplars=0,
        hue_seed=lab.hue_seed,
    )


def _embed_label_text(services: Services, *label_ids: str) -> None:
    """Give new labels a text prior if the model is loaded (otherwise the next inference does it)."""
    st = services.models.status()
    if st.status != "ready":
        return
    model = services.models.get()
    with services.db.connection() as conn:
        mvs = ModelVersionRepo.list(conn)
        maybe = [LabelRepo.get(conn, lid) for lid in label_ids]
    labs = [lab for lab in maybe if lab is not None]
    if not labs:
        return
    for mv in mvs:
        if mv.name != model.name or mv.revision != model.revision:
            continue
        with services.models.lock:
            vecs = model.embed_text(
                [lab.text_prompt or f"The sound of {lab.name}." for lab in labs]
            )
        with services.db.transaction() as conn:
            for lab, v in zip(labs, vecs, strict=True):
                LabelRepo.set_text_vec(conn, lab.id, v, mv.id)


# ------------------------------------------------------------------------------ annotations


@router.post(
    "/recordings/{recording_id}/annotations", response_model=AnnotationResult, status_code=201
)
def submit_annotation(
    body: AnnotationIn,
    recording_id: str = Depends(valid_recording_id),
    services: Services = Depends(get_services),
) -> AnnotationResult:
    req = AnnotationRequest(
        label_ids=body.label_ids,
        new_labels=body.new_labels,
        rejected_label_ids=body.rejected_label_ids,
        is_unknown=body.is_unknown,
        descriptors=body.descriptors,
        environment=body.environment,
        mood=body.mood,
        note=body.note,
    )
    try:
        result = services.memory.annotate(recording_id, req)
    except LookupError as e:
        raise NotFound(str(e)) from e
    except ValueError as e:
        raise ValidationFailed(str(e)) from e
    if result["created_label_ids"]:
        _embed_label_text(services, *result["created_label_ids"])
        # new labels need their text prior before the fused ranking can include them
        mvid = _active_model_version_id(services, recording_id)
        if mvid:
            with services.db.transaction() as conn:
                services.memory.rescore_all(conn, mvid)
    with services.db.connection() as conn:
        ann = AnnotationRepo.active(conn, recording_id)
        names = services.memory.label_names(conn)
        fused = PredictionRepo.latest(conn, recording_id, "fused")
    return AnnotationResult(
        annotation=_annotation_out(ann, names),  # type: ignore[arg-type]
        memory_version=result["memory_version"],
        exemplars_added=result["exemplars_added"],
        exemplars_retracted=result["exemplars_retracted"],
        memory_pending=result["memory_pending"],
        created_label_ids=result["created_label_ids"],
        rescored_changes=result["rescored_changes"],
        fused_top=[c for c in fused.results[:5]] if fused else [],
    )


@router.get("/recordings/{recording_id}/annotations", response_model=list[AnnotationOut])
def annotation_history(
    recording_id: str = Depends(valid_recording_id), services: Services = Depends(get_services)
) -> list[AnnotationOut]:
    with services.db.connection() as conn:
        if RecordingRepo.get(conn, recording_id) is None:
            raise NotFound("recording not found")
        rows = AnnotationRepo.history(conn, recording_id)
        names = services.memory.label_names(conn)
    return [_annotation_out(a, names) for a in rows]


# ----------------------------------------------------------------------------------- memory


@router.get("/memory", response_model=MemoryOverview)
def memory_overview(services: Services = Depends(get_services)) -> MemoryOverview:
    with services.db.connection() as conn:
        mvs = ModelVersionRepo.list(conn)
        mvid = mvs[-1].id if mvs else None
        ov = services.memory.overview(conn, mvid)
    return MemoryOverview(**ov, model_version_id=mvid)


# ----------------------------------------------------------------------------------- echo-0

ECHO_TEMPLATES: dict[str, str] = {
    "first_hearing": "I have heard my first sound. I think it may be {top}.",
    "first_hearing_unsure": "I have heard my first sound.",
    "hypothesis": "I hear something. My strongest hypothesis is {top}. I also detect characteristics associated with {second}. Am I correct?",
    "hypothesis_single": "I hear something. My strongest hypothesis is {top}. Am I correct?",
    "remembered_similar": "This resembles something you taught me before: {top}.",
    "unknown_system": "I can hear it. I cannot name it yet. The closest word I have is {top}.",
    "disagreement": "My ears say {ears}. My memory says {memory}. Which is it?",
    "confirmed": "You confirmed {labels}. I will keep this.",
    "corrected": "I called it {from_}. You called it {to}. I will remember your correction.",
    "created": "A new name: {labels}. I had no word for it before.",
    "unknown_user": "You could not name it either. I will keep listening.",
    "memory_changed": "Your correction changed how I hear {n} other recording(s).",
    "inference_failed": "My ears failed on this one. The signal is kept.",
    "analyzing": "Listening again with my ears.",
}


@router.get("/recordings/{recording_id}/echo", response_model=list[EchoLine])
def echo_lines(
    recording_id: str = Depends(valid_recording_id), services: Services = Depends(get_services)
) -> list[EchoLine]:
    """Deterministic ECHO-0 lines, each tied to persisted events for this recording."""
    with services.db.connection() as conn:
        if RecordingRepo.get(conn, recording_id) is None:
            raise NotFound("recording not found")
        events = EventRepo.for_recording(conn, recording_id)
        names = services.memory.label_names(conn)
        fused = PredictionRepo.latest(conn, recording_id, "fused")
        ann = AnnotationRepo.active(conn, recording_id)
        first_inference = conn.execute(
            "SELECT recording_id FROM event WHERE type='AudioInferenceCompleted' ORDER BY created_at LIMIT 1"
        ).fetchone()
    lines: list[EchoLine] = []

    def nm(lid: str) -> str:
        return names.get(lid, ("?", "?"))[1]

    for ev in events:
        t, p, eid = ev["type"], ev["payload"], ev["event_id"]
        if t == "AudioInferenceCompleted":
            top = p.get("top") or []
            if not top:
                continue
            if first_inference and first_inference[0] == recording_id:
                tmpl = "first_hearing_unsure" if p.get("novel") else "first_hearing"
                lines.append(
                    EchoLine(
                        template=tmpl,
                        text=ECHO_TEMPLATES[tmpl].format(top=top[0]["name"]),
                        tags=["model"],
                        event_ids=[eid],
                    )
                )
        elif t == "AudioInferenceFailed":
            lines.append(
                EchoLine(
                    template="inference_failed",
                    text=ECHO_TEMPLATES["inference_failed"],
                    tags=["model"],
                    event_ids=[eid],
                )
            )
        elif t == "PredictionConfirmed":
            lines.append(
                EchoLine(
                    template="confirmed",
                    text=ECHO_TEMPLATES["confirmed"].format(labels=nm(p["label_id"])),
                    tags=["memory"],
                    event_ids=[eid],
                )
            )
        elif t == "PredictionCorrected":
            lines.append(
                EchoLine(
                    template="corrected",
                    text=ECHO_TEMPLATES["corrected"].format(
                        from_=nm(p["from_label_id"]),
                        to=", ".join(nm(x) for x in p["to_label_ids"]) or "unknown",
                    ),
                    tags=["memory"],
                    event_ids=[eid],
                )
            )
        elif t == "CustomCategoryCreated":
            lines.append(
                EchoLine(
                    template="created",
                    text=ECHO_TEMPLATES["created"].format(labels=p["name"]),
                    tags=["memory"],
                    event_ids=[eid],
                )
            )
        elif t == "UnknownSoundObserved" and p.get("by") == "user":
            lines.append(
                EchoLine(
                    template="unknown_user",
                    text=ECHO_TEMPLATES["unknown_user"],
                    tags=["memory"],
                    event_ids=[eid],
                )
            )
        elif (
            t == "AcousticMemoryUpdated"
            and p.get("reason") == "annotation"
            and p.get("rescored_changes")
        ):
            n = len([c for c in p["rescored_changes"] if c["recording_id"] != recording_id])
            if n:
                lines.append(
                    EchoLine(
                        template="memory_changed",
                        text=ECHO_TEMPLATES["memory_changed"].format(n=n),
                        tags=["memory"],
                        event_ids=[eid],
                    )
                )
    # current hypothesis line (from the persisted fused prediction, only before annotation)
    if fused and fused.results and ann is None:
        nov = fused.novelty or {}
        top = fused.results[0]
        second = fused.results[1] if len(fused.results) > 1 else None
        if nov.get("novel"):
            lines.append(
                EchoLine(
                    template="unknown_system",
                    text=ECHO_TEMPLATES["unknown_system"].format(top=top["name"]),
                    tags=["model"],
                    event_ids=[],
                )
            )
        elif nov.get("disagreement") and nov.get("memory_top"):
            lines.append(
                EchoLine(
                    template="disagreement",
                    text=ECHO_TEMPLATES["disagreement"].format(
                        ears=nm(nov["ears_top"]), memory=nm(nov["memory_top"])
                    ),
                    tags=["model", "memory"],
                    event_ids=[],
                )
            )
        elif (
            top.get("evidence") in ("memory", "both")
            and (top.get("memory_similarity") or 0) >= services.memory.params().tau_memory_strong
        ):
            lines.append(
                EchoLine(
                    template="remembered_similar",
                    text=ECHO_TEMPLATES["remembered_similar"].format(top=top["name"]),
                    tags=["memory"],
                    event_ids=[],
                )
            )
        elif second and second.get("base_similarity", 0) > 0.25:
            lines.append(
                EchoLine(
                    template="hypothesis",
                    text=ECHO_TEMPLATES["hypothesis"].format(
                        top=top["name"], second=second["name"]
                    ),
                    tags=["model"],
                    event_ids=[],
                )
            )
        else:
            lines.append(
                EchoLine(
                    template="hypothesis_single",
                    text=ECHO_TEMPLATES["hypothesis_single"].format(top=top["name"]),
                    tags=["model"],
                    event_ids=[],
                )
            )
    return lines
