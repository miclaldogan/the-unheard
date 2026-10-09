"""M4 endpoints: compositions (the Impossible Orchestra)."""

from __future__ import annotations

import io
import zipfile
from typing import Any

from fastapi import APIRouter, Depends, Query, Response
from fastapi.responses import FileResponse

from unheard.api.deps import Services, get_services, require_token, valid_recording_id
from unheard.api.schemas_m4 import (
    CompositionIn,
    CompositionListItem,
    CompositionOut,
    CompositionPatch,
    EventOut,
    SourceOut,
    TraceOut,
    TrackOut,
    VariationIn,
)
from unheard.errors import NotFound, NotReady
from unheard.storage.ids import is_valid_id
from unheard.storage.repos import RecordingRepo
from unheard.storage.repos_m4 import CompositionRepo, CompositionRow

router = APIRouter(dependencies=[Depends(require_token)])


def _valid_cid(composition_id: str) -> str:
    if not is_valid_id(composition_id):
        raise NotFound("composition not found")
    return composition_id


def _label(services: Services, recording_id: str) -> str | None:
    try:
        v = services.visual.get(recording_id)
    except Exception:  # noqa: BLE001 - labels are decoration, never fatal
        return None
    if v is None:
        return None
    sem = v.params.get("semantic") or {}
    return sem.get("label") if isinstance(sem, dict) else None


def _out(services: Services, row: CompositionRow, *, created: bool | None = None) -> CompositionOut:
    with services.db.connection() as conn:
        srcs = CompositionRepo.sources(conn, row.id)
        tracks = CompositionRepo.tracks(conn, row.id)
        plan = CompositionRepo.plan(conn, row.id)
        exists = {
            s["recording_id"]: RecordingRepo.get(conn, s["recording_id"]) is not None for s in srcs
        }
    names = {
        s["recording_id"]: (_label(services, s["recording_id"]) or "a sound")
        for s in srcs
        if exists[s["recording_id"]]
    }
    base = f"/api/compositions/{row.id}"
    ready = row.status == "ready"
    return CompositionOut(
        id=row.id,
        parent_id=row.parent_id,
        name=row.name,
        saved=row.saved,
        status=row.status,  # type: ignore[arg-type]
        error=row.error,
        seed=row.seed,
        controls=row.controls,
        target_duration_s=row.target_duration_s,
        duration_s=row.duration_s,
        tempo_bpm=row.tempo_bpm,
        planner_version=row.planner_version,
        render_version=row.render_version,
        analysis_version=row.analysis_version,
        dsp_version=row.dsp_version,
        plan_hash=row.plan_hash,
        master_sha256=row.master_sha256,
        master_url=f"{base}/master" if ready else None,
        export_url=f"{base}/export" if ready else None,
        metrics=row.metrics,
        sections=(plan or {}).get("sections", []),
        key=(plan or {}).get("key"),
        tempo_source=(plan or {}).get("tempo_source"),
        sources=[
            SourceOut(
                position=s["position"],
                recording_id=s["recording_id"],
                content_hash=s["content_hash"],
                exists=exists[s["recording_id"]],
                label=names.get(s["recording_id"]),
                role=s["role"],
                secondary_role=s["secondary_role"],
                decision=s["decision"],
                analysis=s["analysis"],
            )
            for s in srcs
        ],
        tracks=[
            TrackOut(
                track_key=t["track_key"],
                recording_id=t["recording_id"],
                role=t["role"],
                layer_order=t["layer_order"],
                pan=t["pan"],
                enters=t["enters"],
                stem_url=f"{base}/stems/{t['track_key']}" if t["stem_path"] else None,
                original_url=f"/api/recordings/{t['recording_id']}/audio",
            )
            for t in tracks
        ],
        echo=services.compositions.echo_lines(row, srcs, names),
        created_at=row.created_at,
        updated_at=row.updated_at,
        rendered_at=row.rendered_at,
        created=created,
    )


@router.post("/compositions", response_model=CompositionOut, status_code=202)
def create_composition(
    body: CompositionIn, response: Response, services: Services = Depends(get_services)
) -> CompositionOut:
    for rid in body.recording_ids:
        valid_recording_id(rid)
    row, created = services.compositions.create(
        body.recording_ids,
        seed=body.seed,
        controls=body.controls,
        duration_s=body.duration_s,
        role_overrides=body.role_overrides,
        name=body.name,
    )
    if not created:
        response.status_code = 200
    return _out(services, row, created=created)


@router.get("/compositions", response_model=list[CompositionListItem])
def list_compositions(
    recording_id: str | None = Query(default=None), services: Services = Depends(get_services)
) -> list[CompositionListItem]:
    if recording_id is not None:
        valid_recording_id(recording_id)
    with services.db.connection() as conn:
        rows = CompositionRepo.all(conn, recording_id=recording_id)
        out = []
        for r in rows:
            srcs = CompositionRepo.sources(conn, r.id)
            out.append(
                CompositionListItem(
                    id=r.id,
                    parent_id=r.parent_id,
                    name=r.name,
                    saved=r.saved,
                    status=r.status,
                    seed=r.seed,
                    duration_s=r.duration_s,
                    tempo_bpm=r.tempo_bpm,
                    n_sources=len(srcs),
                    recording_ids=[s["recording_id"] for s in srcs],
                    created_at=r.created_at,
                )
            )
    return out


@router.get("/compositions/{composition_id}", response_model=CompositionOut)
def get_composition(
    composition_id: str = Depends(_valid_cid), services: Services = Depends(get_services)
) -> CompositionOut:
    return _out(services, services.compositions.get(composition_id))


@router.patch("/compositions/{composition_id}", response_model=CompositionOut)
def patch_composition(
    body: CompositionPatch,
    composition_id: str = Depends(_valid_cid),
    services: Services = Depends(get_services),
) -> CompositionOut:
    services.compositions.get(composition_id)
    with services.db.transaction() as conn:
        CompositionRepo.patch(conn, composition_id, name=body.name, saved=body.saved)
    return _out(services, services.compositions.get(composition_id))


@router.delete("/compositions/{composition_id}", status_code=204)
def delete_composition(
    composition_id: str = Depends(_valid_cid), services: Services = Depends(get_services)
) -> Response:
    services.compositions.delete(composition_id)
    return Response(status_code=204)


@router.post(
    "/compositions/{composition_id}/variation", response_model=CompositionOut, status_code=202
)
def make_variation(
    body: VariationIn,
    response: Response,
    composition_id: str = Depends(_valid_cid),
    services: Services = Depends(get_services),
) -> CompositionOut:
    row, created = services.compositions.variation(
        composition_id, seed=body.seed, controls=body.controls
    )
    if not created:
        response.status_code = 200
    return _out(services, row, created=created)


@router.post(
    "/compositions/{composition_id}/render", response_model=CompositionOut, status_code=202
)
def rerender(
    composition_id: str = Depends(_valid_cid), services: Services = Depends(get_services)
) -> CompositionOut:
    return _out(services, services.compositions.retry(composition_id))


@router.get("/compositions/{composition_id}/events", response_model=list[EventOut])
def composition_events(
    composition_id: str = Depends(_valid_cid), services: Services = Depends(get_services)
) -> list[EventOut]:
    services.compositions.get(composition_id)
    with services.db.connection() as conn:
        return [EventOut(**e) for e in CompositionRepo.events(conn, composition_id)]


@router.get("/compositions/{composition_id}/trace/{seq}", response_model=TraceOut)
def trace_event(
    seq: int, composition_id: str = Depends(_valid_cid), services: Services = Depends(get_services)
) -> TraceOut:
    """Composition → track → event → source recording → visual specimen."""
    services.compositions.get(composition_id)
    with services.db.connection() as conn:
        evs = [e for e in CompositionRepo.events(conn, composition_id) if e["seq"] == seq]
        if not evs:
            raise NotFound("event not found")
        ev = evs[0]
        track = next(
            (
                t
                for t in CompositionRepo.tracks(conn, composition_id)
                if t["track_key"] == ev["track_key"]
            ),
            {},
        )
        rec = RecordingRepo.get(conn, ev["recording_id"])
        also = [
            c
            for c in CompositionRepo.ids_for_recording(conn, ev["recording_id"])
            if c != composition_id
        ]
    source: dict[str, Any] = {"recording_id": ev["recording_id"], "exists": rec is not None}
    specimen = None
    if rec is not None:
        source |= {
            "content_hash": rec.content_hash,
            "captured_at": rec.captured_at,
            "duration_s": rec.duration_s,
            "label": _label(services, rec.id),
            "audio_url": f"/api/recordings/{rec.id}/audio",
        }
        v = services.visual.get(rec.id)
        if v is not None:
            specimen = {
                "artifact_id": v.id,
                "geometry_hash": v.geometry_hash,
                "generator_version": v.generator_version,
            }
    return TraceOut(
        composition_id=composition_id,
        event=EventOut(**ev),
        track={k: track.get(k) for k in ("track_key", "role", "layer_order", "pan", "enters")},
        source=source,
        specimen=specimen,
        also_in=also,
    )


def _file(
    services: Services, rel: str | None, name: str, *, attachment: bool = False
) -> FileResponse:
    if not rel:
        raise NotReady("composition audio is not ready")
    path = services.blobs.absolute(rel)
    if not path.is_file():
        raise NotFound("audio file is missing")
    headers = {"Content-Disposition": f'attachment; filename="{name}"'} if attachment else None
    return FileResponse(path, media_type="audio/wav", headers=headers)


@router.get("/compositions/{composition_id}/master")
def master_audio(
    composition_id: str = Depends(_valid_cid), services: Services = Depends(get_services)
) -> FileResponse:
    row = services.compositions.get(composition_id)
    if row.status != "ready":
        raise NotReady(f"composition is {row.status}")
    return _file(services, row.master_path, "master.wav")


@router.get("/compositions/{composition_id}/stems/{track_key}")
def stem_audio(
    track_key: str,
    composition_id: str = Depends(_valid_cid),
    services: Services = Depends(get_services),
) -> FileResponse:
    row = services.compositions.get(composition_id)
    if row.status != "ready":
        raise NotReady(f"composition is {row.status}")
    with services.db.connection() as conn:
        t = next(
            (
                t
                for t in CompositionRepo.tracks(conn, composition_id)
                if t["track_key"] == track_key
            ),
            None,
        )
    if t is None:
        raise NotFound("track not found")
    return _file(services, t["stem_path"], f"{track_key}.wav")


@router.get("/compositions/{composition_id}/export", response_model=None)
def export(
    bundle: bool = Query(default=False, description="zip with master, stems, plan and provenance"),
    composition_id: str = Depends(_valid_cid),
    services: Services = Depends(get_services),
) -> Response | FileResponse:
    row = services.compositions.get(composition_id)
    if row.status != "ready":
        raise NotReady(f"composition is {row.status}")
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in row.name)[:40] or "orchestra"
    if not bundle:
        return _file(services, row.master_path, f"{safe}-{row.id[:8]}.wav", attachment=True)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:
        z.write(services.blobs.absolute(row.master_path or ""), "master.wav")
        with services.db.connection() as conn:
            tracks = CompositionRepo.tracks(conn, composition_id)
        for t in tracks:
            z.write(
                services.blobs.absolute(t["stem_path"]), f"stems/{t['track_key']}-{t['role']}.wav"
            )
        for name in ("plan.json", "provenance.json"):
            z.write(
                services.blobs.absolute(services.blobs.composition_path(composition_id, name)), name
            )
    return Response(
        buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{safe}-{row.id[:8]}.zip"'},
    )
