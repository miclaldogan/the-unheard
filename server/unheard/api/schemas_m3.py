from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class VisualOut(BaseModel):
    artifact_id: str
    recording_id: str
    generator_version: int
    seed: int
    dsp_version: int
    model_version_id: str | None
    geometry_hash: str
    status: Literal["ready", "stale"]
    params: dict[str, Any] = Field(
        description="geometry (measured), animation (measured timelines), semantic (labels/state)"
    )
    created_at: str
    updated_at: str


class AtlasOut(BaseModel):
    atlas_version: int
    layout_version: int
    generator_version: int
    model_version_id: str | None
    model: dict[str, Any] | None
    basis: dict[str, Any] | None
    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]
    anchors: list[dict[str, Any]]
    state: str
    counts: dict[str, int]
    narrative: list[dict[str, Any]]
