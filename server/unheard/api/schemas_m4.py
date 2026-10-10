from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class CompositionIn(BaseModel):
    recording_ids: list[str] = Field(min_length=1, max_length=8)
    mode: Literal["organic", "composed", "legacy"] = Field(
        default="composed",
        description="organic: source-timed, sparse, atmospheric; composed: structured motifs, call-and-response; "
        "legacy: the M4/M4.5 event planner (kept for A/B comparison)",
    )
    seed: int | None = Field(default=None, ge=0, le=2**32 - 1)
    controls: dict[str, float] | None = Field(
        default=None, description="density, structure, intensity in 0…1 (default 0.5 each)"
    )
    duration_s: float | None = Field(default=None, ge=15, le=90)
    role_overrides: dict[str, str] | None = Field(
        default=None,
        description="recording_id → role (texture, drone, rhythmic_texture, percussion, tonal_motif, accent, granular)",
    )
    name: str | None = Field(default=None, max_length=80)


class VariationIn(BaseModel):
    seed: int | None = Field(default=None, ge=0, le=2**32 - 1)
    controls: dict[str, float] | None = None


class CompositionPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    saved: bool | None = None


class SourceOut(BaseModel):
    position: int
    recording_id: str
    content_hash: str
    exists: bool
    label: str | None = None
    role: str | None
    secondary_role: str | None
    decision: dict[str, Any] | None
    analysis: dict[str, Any] | None


class TrackOut(BaseModel):
    track_key: str
    recording_id: str
    role: str
    layer_order: int
    pan: float
    enters: str
    hierarchy: str | None = None
    stem_url: str | None
    original_url: str


class CompositionOut(BaseModel):
    id: str
    parent_id: str | None
    name: str
    saved: bool
    mode: str = "legacy"
    status: Literal["queued", "processing", "ready", "failed"]
    error: str | None
    seed: int
    controls: dict[str, float]
    target_duration_s: float
    duration_s: float | None
    tempo_bpm: float | None
    planner_version: int
    render_version: int
    analysis_version: int
    dsp_version: int
    plan_hash: str | None
    master_sha256: str | None
    master_url: str | None
    export_url: str | None
    metrics: dict[str, Any] | None
    sections: list[dict[str, Any]] = []
    form: dict[str, str] | None = None
    conversation: list[dict[str, Any]] = []
    groove: dict[str, Any] | None = None
    hierarchy: dict[str, Any] | None = None
    key: dict[str, Any] | None = None
    tempo_source: str | None = None
    sources: list[SourceOut] = []
    tracks: list[TrackOut] = []
    echo: list[dict[str, Any]] = []
    created_at: str
    updated_at: str
    rendered_at: str | None
    created: bool | None = None


class CompositionListItem(BaseModel):
    id: str
    parent_id: str | None
    name: str
    saved: bool
    mode: str = "legacy"
    status: str
    seed: int
    duration_s: float | None
    tempo_bpm: float | None
    n_sources: int
    recording_ids: list[str]
    created_at: str


class EventOut(BaseModel):
    seq: int
    track_key: str
    recording_id: str
    kind: str
    role: str
    section: str
    comp_start_s: float
    comp_dur_s: float
    source_start_s: float
    source_end_s: float
    params: dict[str, Any]


class TraceOut(BaseModel):
    composition_id: str
    event: EventOut
    track: dict[str, Any]
    source: dict[str, Any]
    specimen: dict[str, Any] | None
    also_in: list[str]
