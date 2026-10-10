"""Memory service: labels, annotations, exemplars, prototypes, rescoring.

All mutations happen in one SQLite transaction and bump ``memory_version``.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from typing import Any

import numpy as np

from unheard.config import Settings
from unheard.events import (
    ACOUSTIC_MEMORY_UPDATED,
    ANNOTATION_SUBMITTED,
    CUSTOM_CATEGORY_CREATED,
    PREDICTION_CONFIRMED,
    PREDICTION_CORRECTED,
    UNKNOWN_SOUND_OBSERVED,
)
from unheard.memory.engine import FusionParams, FusionResult, MemoryIndex, fuse, prototype
from unheard.models.vocabulary import VOCABULARY, prompt_for
from unheard.storage.db import Database
from unheard.storage.repos import EventRepo, RecordingRepo
from unheard.storage.repos_m2 import (
    AnnotationRepo,
    EmbeddingRepo,
    ExemplarRepo,
    LabelRepo,
    LabelRow,
    MemoryMetaRepo,
    ModelVersionRepo,
    PredictionRepo,
    PredictionRow,
    PrototypeRepo,
    slugify,
)

log = logging.getLogger(__name__)

FUSED_SCORE_KIND = (
    "fused: log-linear(base softmax(cos/t_base), kernel-kNN memory); base_similarity is cosine"
)
BASE_SCORE_KIND = (
    "cosine similarity between CLAP audio and text embeddings (max over windows); not a probability"
)


@dataclass
class AnnotationRequest:
    label_ids: list[str]
    new_labels: list[str]
    rejected_label_ids: list[str]
    is_unknown: bool
    descriptors: list[str]
    environment: str | None
    mood: str | None
    note: str | None


class MemoryService:
    def __init__(self, settings: Settings, db: Database) -> None:
        self.settings = settings
        self.db = db
        self.visual: Any = None  # VisualService (set by Services.build); refreshes semantic layers

    def params(self) -> FusionParams:
        s = self.settings
        return FusionParams(
            k=s.fusion_k,
            t_mem=s.fusion_t_mem,
            kappa=s.fusion_kappa,
            t_base=s.fusion_t_base,
            tau_novel=s.fusion_tau_novel,
            tau_margin=s.fusion_tau_margin,
            tau_entropy=s.fusion_tau_entropy,
            tau_memory_strong=s.fusion_tau_memory_strong,
        )

    # -- label space ----------------------------------------------------------
    def ensure_vocabulary(self, conn: sqlite3.Connection) -> list[LabelRow]:
        for slug, name, phrase in VOCABULARY:
            if LabelRepo.by_slug(conn, slug) is None:
                LabelRepo.create(
                    conn, name=name, origin="vocabulary", text_prompt=prompt_for(phrase), slug=slug
                )
        return LabelRepo.list(conn)

    def labels_needing_text_vec(
        self, conn: sqlite3.Connection, model_version_id: str
    ) -> list[LabelRow]:
        return [
            lab
            for lab in LabelRepo.list(conn)
            if lab.text_model_version_id != model_version_id or lab.text_vec is None
        ]

    def label_space(
        self, conn: sqlite3.Connection, model_version_id: str
    ) -> tuple[list[str], np.ndarray]:
        labs = LabelRepo.with_text_vec(conn, model_version_id)
        if not labs:
            return [], np.zeros((0, 0), np.float32)
        return [lab.id for lab in labs], np.stack(
            [lab.text_vec for lab in labs if lab.text_vec is not None]
        )

    def create_label(
        self,
        conn: sqlite3.Connection,
        name: str,
        *,
        origin: str = "user",
        recording_id: str | None = None,
    ) -> tuple[LabelRow, bool]:
        name = " ".join(name.split())
        if not name or len(name) > self.settings.max_label_name_len:
            raise ValueError(f"label name must be 1–{self.settings.max_label_name_len} characters")
        slug = slugify(name)
        if not slug:
            raise ValueError("label name needs at least one letter or digit")
        existing = LabelRepo.by_slug(conn, slug)
        if existing:
            return existing, False
        lab = LabelRepo.create(conn, name=name, origin=origin, text_prompt=prompt_for(name))
        EventRepo.append(
            conn,
            CUSTOM_CATEGORY_CREATED,
            {"label_id": lab.id, "slug": lab.slug, "name": lab.name},
            recording_id=recording_id,
        )
        return lab, True

    # -- index ---------------------------------------------------------------
    def build_index(
        self,
        conn: sqlite3.Connection,
        model_version_id: str,
        *,
        exclude_recording: str | None = None,
    ) -> MemoryIndex:
        rows = ExemplarRepo.active(conn, model_version_id, exclude_recording=exclude_recording)
        if not rows:
            mv = ModelVersionRepo.get(conn, model_version_id)
            return MemoryIndex.empty(mv.embedding_dim if mv else 0)
        return MemoryIndex(
            vecs=np.stack([r.vec for r in rows]).astype(np.float32),
            label_ids=[r.label_id for r in rows],
            recording_ids=[r.recording_id for r in rows],
            exemplar_ids=[r.id for r in rows],
            weights=np.array([r.weight for r in rows], dtype=np.float32),
        )

    # -- scoring -------------------------------------------------------------
    def fuse_recording(
        self, conn: sqlite3.Connection, recording_id: str, model_version_id: str
    ) -> FusionResult | None:
        base = PredictionRepo.latest(conn, recording_id, "base")
        pooled = EmbeddingRepo.pooled(conn, recording_id, model_version_id)
        if base is None or pooled is None:
            return None
        # Base cosines are recomputed from the stored window embeddings against the *current*
        # label space, so labels created after inference (user names) take part without
        # re-running the audio model. Falls back to the persisted base results.
        label_ids, mat = self.label_space(conn, model_version_id)
        windows = EmbeddingRepo.windows(conn, recording_id, model_version_id)
        if label_ids and windows:
            per_window = np.stack([mat @ w.vec for w in windows])  # (W, L)
            cos = per_window.max(axis=0).astype(np.float64)
        else:
            label_ids = [c["label_id"] for c in base.results]
            cos = np.array([c["similarity"] for c in base.results], dtype=np.float64)
        # a recording's own exemplars must not vote for itself (that would be memorisation)
        index = self.build_index(conn, model_version_id, exclude_recording=recording_id)
        return fuse(pooled.vec, label_ids, cos, index, self.params())

    def store_fused(
        self,
        conn: sqlite3.Connection,
        recording_id: str,
        model_version_id: str,
        result: FusionResult,
        names: dict[str, tuple[str, str]],
    ) -> str:
        results = [
            {
                "label_id": c.label_id,
                "slug": names.get(c.label_id, (c.label_id, c.label_id))[0],
                "name": names.get(c.label_id, (c.label_id, c.label_id))[1],
                "rank": c.rank,
                "fused_score": round(c.fused_score, 6),
                "base_similarity": round(c.base_similarity, 6),
                "base_score": round(c.base_score, 6),
                "memory_similarity": None
                if c.memory_similarity is None
                else round(c.memory_similarity, 6),
                "memory_score": None if c.memory_score is None else round(c.memory_score, 6),
                "n_exemplars": c.n_exemplars,
                "lambda": round(c.lambda_, 4),
                "evidence": c.evidence,
            }
            for c in result.candidates
        ]
        novelty = dict(result.novelty)
        novelty["neighbours"] = [
            {
                "exemplar_id": n.exemplar_id,
                "recording_id": n.recording_id,
                "label_id": n.label_id,
                "similarity": round(n.similarity, 6),
            }
            for n in result.neighbours
        ]
        version = MemoryMetaRepo.version(conn)
        PredictionRepo.delete_kind(conn, recording_id, "fused")
        pid = PredictionRepo.insert(
            conn,
            recording_id=recording_id,
            model_version_id=model_version_id,
            kind="fused",
            memory_version=version,
            score_kind=FUSED_SCORE_KIND,
            results=results,
            windows=None,
            novelty=novelty,
            inference_ms=None,
        )
        return pid

    def label_names(self, conn: sqlite3.Connection) -> dict[str, tuple[str, str]]:
        return {lab.id: (lab.slug, lab.name) for lab in LabelRepo.list(conn)}

    def rescore_all(self, conn: sqlite3.Connection, model_version_id: str) -> list[dict[str, Any]]:
        """Recompute fused predictions for every recording with an embedding; return diffs."""
        names = self.label_names(conn)
        changes: list[dict[str, Any]] = []
        for emb in EmbeddingRepo.all_pooled(conn, model_version_id):
            before = PredictionRepo.latest(conn, emb.recording_id, "fused")
            res = self.fuse_recording(conn, emb.recording_id, model_version_id)
            if res is None or not res.candidates:
                continue
            self.store_fused(conn, emb.recording_id, model_version_id, res, names)
            old_top = before.results[0]["label_id"] if before and before.results else None
            new_top = res.candidates[0].label_id
            if old_top != new_top:
                changes.append(
                    {
                        "recording_id": emb.recording_id,
                        "from": names.get(old_top, (None, None))[1] if old_top else None,
                        "to": names[new_top][1],
                    }
                )
        return changes

    # -- annotation ------------------------------------------------------------
    def annotate(self, recording_id: str, req: AnnotationRequest) -> dict[str, Any]:
        s = self.settings
        if len(req.label_ids) + len(req.new_labels) > s.max_labels_per_annotation:
            raise ValueError(f"at most {s.max_labels_per_annotation} source labels per annotation")
        if len(req.descriptors) > s.max_descriptors:
            raise ValueError(f"at most {s.max_descriptors} descriptors")
        with self.db.transaction() as conn:
            rec = RecordingRepo.get(conn, recording_id)
            if rec is None:
                raise LookupError("recording not found")
            label_ids: list[str] = []
            created: list[str] = []
            for lid in req.label_ids:
                lab = LabelRepo.get(conn, lid)
                if lab is None or lab.merged_into:
                    raise ValueError(f"unknown label id {lid}")
                if lab.id not in label_ids:
                    label_ids.append(lab.id)
            for name in req.new_labels:
                lab, new = self.create_label(conn, name, recording_id=recording_id)
                if new:
                    created.append(lab.id)
                if lab.id not in label_ids:
                    label_ids.append(lab.id)
            if req.is_unknown:
                label_ids = []
            if not req.is_unknown and not label_ids:
                raise ValueError("choose at least one source label, or mark the sound as unknown")
            rejected = [lid for lid in req.rejected_label_ids if lid not in label_ids]

            previous = AnnotationRepo.active(conn, recording_id)
            base = PredictionRepo.latest(conn, recording_id, "base")
            fused = PredictionRepo.latest(conn, recording_id, "fused")
            shown = fused or base
            action = (
                "unknown"
                if req.is_unknown
                else "create"
                if created
                else ("correct" if previous else self._confirm_or_correct(shown, label_ids))
            )
            ann_id = AnnotationRepo.insert(
                conn,
                recording_id=recording_id,
                action=action,
                label_ids=label_ids,
                rejected_label_ids=rejected,
                is_unknown=req.is_unknown,
                descriptors=req.descriptors,
                environment=req.environment,
                mood=req.mood,
                note=req.note,
                prediction_id=shown.id if shown else None,
            )
            retracted = 0
            if previous:
                AnnotationRepo.supersede(conn, previous.id, ann_id)
                retracted = ExemplarRepo.retract_for_annotation(conn, previous.id)

            # exemplars: pooled embedding × each source label (only if the model has run)
            model_version_id = base.model_version_id if base else None
            added = 0
            touched: set[str] = set(previous.label_ids) if previous else set()
            if model_version_id and label_ids:
                pooled = EmbeddingRepo.pooled(conn, recording_id, model_version_id)
                if pooled is not None:
                    for lid in label_ids:
                        ExemplarRepo.insert(
                            conn,
                            annotation_id=ann_id,
                            embedding_id=pooled.id,
                            recording_id=recording_id,
                            label_id=lid,
                        )
                        added += 1
                        touched.add(lid)
            version = MemoryMetaRepo.bump(conn)
            if model_version_id:
                self._recompute_prototypes(conn, model_version_id, touched, version)

            payload = {
                "annotation_id": ann_id,
                "action": action,
                "label_ids": label_ids,
                "rejected_label_ids": rejected,
                "is_unknown": req.is_unknown,
                "created_label_ids": created,
                "superseded": previous.id if previous else None,
                "memory_version": version,
            }
            EventRepo.append(conn, ANNOTATION_SUBMITTED, payload, recording_id=recording_id)
            if req.is_unknown:
                EventRepo.append(
                    conn,
                    UNKNOWN_SOUND_OBSERVED,
                    {"annotation_id": ann_id, "by": "user"},
                    recording_id=recording_id,
                )
            elif shown and shown.results:
                top = shown.results[0]["label_id"]
                if top in label_ids and not previous:
                    EventRepo.append(
                        conn,
                        PREDICTION_CONFIRMED,
                        {"label_id": top, "annotation_id": ann_id},
                        recording_id=recording_id,
                    )
                elif top not in label_ids:
                    EventRepo.append(
                        conn,
                        PREDICTION_CORRECTED,
                        {"from_label_id": top, "to_label_ids": label_ids, "annotation_id": ann_id},
                        recording_id=recording_id,
                    )
            changes = self.rescore_all(conn, model_version_id) if model_version_id else []
            EventRepo.append(
                conn,
                ACOUSTIC_MEMORY_UPDATED,
                {
                    "memory_version": version,
                    "exemplars_added": added,
                    "exemplars_retracted": retracted,
                    "rescored_changes": changes,
                    "reason": "annotation",
                },
                recording_id=recording_id,
            )
            result = {
                **payload,
                "memory_pending": bool(label_ids) and added == 0,
                "exemplars_added": added,
                "exemplars_retracted": retracted,
                "rescored_changes": changes,
            }
        self._refresh_visuals([recording_id] + [c["recording_id"] for c in changes])
        return result

    def backfill_pending(
        self, conn: sqlite3.Connection, recording_id: str, model_version_id: str
    ) -> dict[str, Any] | None:
        """Turn an annotation made before inference into exemplars, exactly once.

        Called inside the inference transaction after the recording's embedding is stored. Only the
        *active* annotation counts (a correction made while inference was pending already superseded
        the older one), and an annotation that already has an exemplar is left alone, so retries and
        re-inference are idempotent.
        """
        ann = AnnotationRepo.active(conn, recording_id)
        if ann is None or ann.is_unknown or not ann.label_ids:
            return None
        if conn.execute(
            "SELECT 1 FROM exemplar WHERE annotation_id=? LIMIT 1", (ann.id,)
        ).fetchone():
            return None
        pooled = EmbeddingRepo.pooled(conn, recording_id, model_version_id)
        if pooled is None:
            return None
        for lid in ann.label_ids:
            ExemplarRepo.insert(
                conn,
                annotation_id=ann.id,
                embedding_id=pooled.id,
                recording_id=recording_id,
                label_id=lid,
            )
        version = MemoryMetaRepo.bump(conn)
        self._recompute_prototypes(conn, model_version_id, set(ann.label_ids), version)
        changes = self.rescore_all(conn, model_version_id)
        EventRepo.append(
            conn,
            ACOUSTIC_MEMORY_UPDATED,
            {
                "memory_version": version,
                "exemplars_added": len(ann.label_ids),
                "exemplars_retracted": 0,
                "rescored_changes": changes,
                "reason": "annotation_backfill",
                "annotation_id": ann.id,
            },
            recording_id=recording_id,
        )
        return {"annotation_id": ann.id, "exemplars_added": len(ann.label_ids), "changes": changes}

    def _refresh_visuals(self, recording_ids: list[str]) -> None:
        if self.visual is None:
            return
        for rid in dict.fromkeys(recording_ids):
            try:
                self.visual.ensure_artifact(rid)
            except Exception:  # noqa: BLE001
                log.exception("visual refresh failed for %s", rid)

    @staticmethod
    def _confirm_or_correct(shown: PredictionRow | None, label_ids: list[str]) -> str:
        if shown and shown.results and shown.results[0]["label_id"] in label_ids:
            return "confirm"
        return "correct"

    def _recompute_prototypes(
        self, conn: sqlite3.Connection, model_version_id: str, label_ids: set[str], version: int
    ) -> None:
        for lid in label_ids:
            rows = ExemplarRepo.for_label(conn, lid, model_version_id)
            if not rows:
                PrototypeRepo.delete(conn, lid, model_version_id)
                continue
            vec, n_eff, sigma = prototype(
                np.stack([r.vec for r in rows]), np.array([r.weight for r in rows])
            )
            PrototypeRepo.upsert(
                conn,
                label_id=lid,
                model_version_id=model_version_id,
                vec=vec,
                n_eff=n_eff,
                sigma=sigma,
                memory_version=version,
            )

    def on_recording_deleted(
        self,
        conn: sqlite3.Connection,
        recording_id: str,
        label_ids: list[str],
        model_version_id: str | None,
    ) -> None:
        """Called inside the delete transaction after cascades: fix prototypes + rescore."""
        version = MemoryMetaRepo.bump(conn)
        if model_version_id:
            self._recompute_prototypes(conn, model_version_id, set(label_ids), version)
            changes = self.rescore_all(conn, model_version_id)
        else:
            changes = []
        EventRepo.append(
            conn,
            ACOUSTIC_MEMORY_UPDATED,
            {"memory_version": version, "reason": "delete", "rescored_changes": changes},
            recording_id=recording_id,
        )

    # -- summaries -------------------------------------------------------------
    def overview(self, conn: sqlite3.Connection, model_version_id: str | None) -> dict[str, Any]:
        names = self.label_names(conn)
        counts = ExemplarRepo.counts_by_label(conn, model_version_id) if model_version_id else {}
        protos = PrototypeRepo.all(conn, model_version_id) if model_version_id else {}
        labels = []
        for lab in LabelRepo.list(conn):
            n = counts.get(lab.id, 0)
            if n == 0 and lab.origin == "vocabulary":
                continue
            ex = (
                ExemplarRepo.for_label(conn, lab.id, model_version_id)
                if (model_version_id and n)
                else []
            )
            p = protos.get(lab.id)
            labels.append(
                {
                    "label_id": lab.id,
                    "slug": lab.slug,
                    "name": lab.name,
                    "origin": lab.origin,
                    "n_exemplars": n,
                    "hue_seed": lab.hue_seed,
                    "recording_ids": [r.recording_id for r in ex],
                    "prototype": None
                    if p is None
                    else {"n_eff": round(p[1], 3), "sigma": round(p[2], 4)},
                }
            )
        anns = AnnotationRepo.active_for_all(conn)
        return {
            "memory_version": MemoryMetaRepo.version(conn),
            "exemplars": int(sum(counts.values())),
            "annotations": len(anns),
            "unknown_annotations": sum(1 for a in anns if a.is_unknown),
            "custom_labels": sum(1 for lab in LabelRepo.list(conn) if lab.origin == "user"),
            "labels": labels,
            "label_names": {k: v[1] for k, v in names.items()},
        }
