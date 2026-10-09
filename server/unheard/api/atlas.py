"""M3 endpoints: visual artifacts and the acoustic atlas."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from unheard.api.deps import Services, get_services, require_token, valid_recording_id
from unheard.api.schemas_m3 import AtlasOut, VisualOut
from unheard.errors import NotFound, NotReady
from unheard.storage.repos import RecordingRepo

router = APIRouter(dependencies=[Depends(require_token)])


def _visual_out(row) -> VisualOut:  # type: ignore[no-untyped-def]
    return VisualOut(
        artifact_id=row.id,
        recording_id=row.recording_id,
        generator_version=row.generator_version,
        seed=row.seed,
        dsp_version=row.dsp_version,
        model_version_id=row.model_version_id,
        geometry_hash=row.geometry_hash,
        status=row.status,
        params=row.params,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.get("/recordings/{recording_id}/visual", response_model=VisualOut)
def get_visual(
    recording_id: str = Depends(valid_recording_id), services: Services = Depends(get_services)
) -> VisualOut:
    with services.db.connection() as conn:
        rec = RecordingRepo.get(conn, recording_id)
    if rec is None:
        raise NotFound("recording not found")
    row = services.visual.get(recording_id)
    if row is None:
        raise NotReady(
            "features are not ready yet; the specimen cannot be drawn", extra={"status": rec.status}
        )
    return _visual_out(row)


@router.get("/atlas", response_model=AtlasOut)
def get_atlas(services: Services = Depends(get_services)) -> AtlasOut:
    payload = services.atlas.build()
    with services.db.connection() as conn:
        narrative = services.atlas.narrative(conn, payload)
    return AtlasOut(**payload, narrative=narrative)


@router.post("/atlas/rebuild", response_model=AtlasOut)
def rebuild_atlas(services: Services = Depends(get_services)) -> AtlasOut:
    payload = services.atlas.build(rebuild=True)
    with services.db.connection() as conn:
        narrative = services.atlas.narrative(conn, payload)
    return AtlasOut(**payload, narrative=narrative)
