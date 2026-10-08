"""Pydantic response models (the API contract documented in docs/api.md)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

RecordingStatus = Literal["uploaded", "processing", "ready", "failed"]


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    version: str
    api_version: str = "1"
    dsp_version: int
    schema_version: int
    inference: Literal["local", "remote"] = "local"
    model_loaded: bool = False
    decoder: dict[str, Any]
    limits: dict[str, Any]
    recordings: int
    free_disk_bytes: int | None
    python: str


class ErrorInfo(BaseModel):
    stage: str | None = None
    message: str
    attempts: int | None = None


class JobInfo(BaseModel):
    id: str
    stage: str
    status: Literal["queued", "running", "done", "failed"]
    attempts: int
    error: str | None
    updated_at: str


class AssetInfo(BaseModel):
    kind: Literal["source", "canonical"]
    container: str | None
    codec: str | None
    sample_rate: int
    channels: int
    sample_format: str | None
    bytes: int


class InferenceInfo(BaseModel):
    """Model adapter result. In M1 always ``status="not_run"`` (no model installed)."""

    status: Literal["not_run", "ok", "failed", "unavailable"]
    model_id: str | None = None
    model_version: str | None = None
    predictions: list[dict[str, Any]] = Field(default_factory=list)
    embedding: dict[str, Any] | None = None
    error: dict[str, Any] | None = None


class RecordingSummary(BaseModel):
    id: str
    created_at: str
    captured_at: str | None
    original_filename: str | None
    duration_s: float
    status: RecordingStatus
    quality: dict[str, Any]
    error: ErrorInfo | None
    dsp_version: int | None = None


class RecordingDetail(RecordingSummary):
    content_hash: str
    source_hash: str
    client_mime: str | None
    device_info: dict[str, Any] | None
    assets: list[AssetInfo]
    jobs: list[JobInfo]
    features: dict[str, Any] | None
    inference: InferenceInfo
    links: dict[str, str]


class RecordingList(BaseModel):
    items: list[RecordingSummary]
    total: int
    limit: int
    offset: int


class UploadAccepted(BaseModel):
    recording_id: str
    status: RecordingStatus
    duration_s: float
    quality: dict[str, Any]
    links: dict[str, str]


class FeatureSeries(BaseModel):
    times_s: list[float]
    rms_envelope_db: list[float]
    centroid_hz: list[float]
    bandwidth_hz: list[float]
    rolloff_hz: list[float]
    flatness: list[float]
    flux: list[float]


class WaveformSummary(BaseModel):
    buckets: int
    duration_s: float
    min: list[float]
    max: list[float]
    rms: list[float]


class FeaturesResponse(BaseModel):
    recording_id: str
    dsp_version: int
    artifact_sha256: str
    summary: dict[str, Any]
    waveform: WaveformSummary
    series: FeatureSeries
    onset_strength: list[float]
    onset_times_s: list[float]


class SpectrogramResponse(BaseModel):
    recording_id: str
    kind: Literal["mel", "stft"]
    dsp_version: int
    unit: Literal["dB"] = "dB"
    n_bins: int
    n_frames: int
    frames_pooled: int = Field(description="how many original frames each returned frame averages")
    duration_s: float
    freqs_hz: list[float]
    times_s: list[float]
    min_db: float
    max_db: float
    values: list[list[float]] = Field(description="n_bins rows × n_frames columns")
