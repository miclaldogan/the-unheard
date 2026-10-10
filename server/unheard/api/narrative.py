"""M5 endpoints: ECHO-0's narrative layer. See docs/contracts/M5-NARRATIVE-API.md (contract m5.1)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response

from unheard.api.deps import Services, get_services, require_token
from unheard.api.schemas_m5 import (
    CurrentOut,
    EchoOut,
    MissionOut,
    MissionsOut,
    ModelStatusOut,
    SettingsIn,
    SettingsOut,
    StateOut,
    TimelineOut,
)
from unheard.errors import NotFound
from unheard.narrative import CONTRACT_VERSION
from unheard.storage.ids import is_valid_id

router = APIRouter(prefix="/narrative", dependencies=[Depends(require_token)])


@router.get("/state", response_model=StateOut)
def state(services: Services = Depends(get_services)) -> dict:  # type: ignore[type-arg]
    return services.narrative.state()


@router.get("/current", response_model=CurrentOut)
def current(
    wait_ms: int = Query(default=0, ge=0, le=8000), services: Services = Depends(get_services)
) -> dict:  # type: ignore[type-arg]
    return services.narrative.current(wait_ms)


@router.get("/timeline", response_model=TimelineOut)
def timeline(
    limit: int = Query(default=50, ge=1, le=200),
    before: str | None = Query(default=None, max_length=40),
    services: Services = Depends(get_services),
) -> dict:  # type: ignore[type-arg]
    return services.narrative.timeline(limit, before)


@router.get("/echo", response_model=EchoOut)
def echo(
    recording_id: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    services: Services = Depends(get_services),
) -> dict:  # type: ignore[type-arg]
    if recording_id is not None and not is_valid_id(recording_id):
        raise NotFound("recording not found")
    return services.narrative.echo(recording_id, limit)


@router.get("/missions", response_model=MissionsOut)
def missions(services: Services = Depends(get_services)) -> dict:  # type: ignore[type-arg]
    return services.narrative.missions()


@router.post("/missions/{mission_id}/activate", response_model=MissionOut)
def activate(
    mission_id: str, response: Response, services: Services = Depends(get_services)
) -> dict:  # type: ignore[type-arg]
    if not (mission_id.startswith("msn_") and len(mission_id) <= 32):
        from unheard.narrative.service import MissionNotFound

        raise MissionNotFound("no mission with that id")
    mission, created = services.narrative.activate(mission_id)
    response.status_code = 201 if created else 200
    return mission


@router.get("/compositions/{composition_id}/commentary", response_model=CurrentOut)
def commentary(
    composition_id: str,
    wait_ms: int = Query(default=0, ge=0, le=8000),
    services: Services = Depends(get_services),
) -> dict:  # type: ignore[type-arg]
    if not is_valid_id(composition_id):
        raise NotFound("composition not found")
    return services.narrative.commentary(composition_id, wait_ms)


@router.get("/model-status", response_model=ModelStatusOut)
def model_status(services: Services = Depends(get_services)) -> dict:  # type: ignore[type-arg]
    return services.narrative.model_status()


@router.patch("/settings", response_model=SettingsOut)
def patch_settings(body: SettingsIn, services: Services = Depends(get_services)) -> dict:  # type: ignore[type-arg]
    services.narrative.set_gemma_enabled(body.gemma_enabled)
    return {
        "contract_version": CONTRACT_VERSION,
        "gemma_enabled": services.narrative.gemma_enabled(),
    }
