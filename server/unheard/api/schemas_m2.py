"""Pydantic models for the M2 endpoints."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

PredictionState = Literal[
    "model_disabled", "not_run", "analyzing", "inference_failed", "awaiting_feedback", "remembered"
]


class ModelStatusOut(BaseModel):
    status: str
    model_id: str | None
    revision: str | None
    device: str
    embedding_dim: int | None
    preprocessing_version: int
    load_seconds: float | None
    error: str | None
    inference: Literal["local", "remote"] = "local"
    known_versions: list[dict[str, Any]] = Field(default_factory=list)


class PredictionOut(BaseModel):
    recording_id: str
    state: PredictionState
    model_status: str
    model: dict[str, Any] | None
    job: dict[str, Any] | None
    base: dict[str, Any] | None = Field(
        description="ears only: cosine similarities, max over windows"
    )
    fused: dict[str, Any] | None = Field(
        description="ears + personal memory at memory_version; includes novelty"
    )
    annotation: AnnotationOut | None


class NeighbourOut(BaseModel):
    recording_id: str
    similarity: float
    labels: list[str]
    is_unknown: bool
    captured_at: str | None
    duration_s: float | None


class LabelIn(BaseModel):
    name: str = Field(min_length=1, max_length=48)


class LabelOut(BaseModel):
    id: str
    slug: str
    name: str
    origin: Literal["vocabulary", "user"]
    n_exemplars: int
    hue_seed: int


def _clean_list(v: list[str], max_items: int, max_len: int) -> list[str]:
    if len(v) > max_items:
        raise ValueError(f"at most {max_items} items")
    out: list[str] = []
    for item in v:
        t = " ".join(str(item).split())
        if len(t) > max_len:
            raise ValueError(f"item longer than {max_len} characters")
        if t and t not in out:
            out.append(t)
    return out


class AnnotationIn(BaseModel):
    label_ids: list[str] = Field(default_factory=list, max_length=6)
    new_labels: list[str] = Field(default_factory=list, max_length=3)
    rejected_label_ids: list[str] = Field(default_factory=list, max_length=20)
    is_unknown: bool = False
    descriptors: list[str] = Field(default_factory=list, max_length=10)
    environment: str | None = Field(default=None, max_length=80)
    mood: str | None = Field(default=None, max_length=80)
    note: str | None = Field(default=None, max_length=500)

    @field_validator("new_labels")
    @classmethod
    def _labels(cls, v: list[str]) -> list[str]:
        return _clean_list(v, 3, 48)

    @field_validator("descriptors")
    @classmethod
    def _desc(cls, v: list[str]) -> list[str]:
        return _clean_list(v, 10, 32)

    @field_validator("label_ids", "rejected_label_ids")
    @classmethod
    def _ids(cls, v: list[str]) -> list[str]:
        from unheard.storage.ids import is_valid_id

        bad = [x for x in v if not is_valid_id(x)]
        if bad:
            raise ValueError("invalid label id")
        return list(dict.fromkeys(v))


class AnnotationOut(BaseModel):
    id: str
    recording_id: str
    action: Literal["confirm", "correct", "create", "unknown"]
    status: Literal["active", "superseded"]
    labels: list[dict[str, str]]
    rejected_label_ids: list[str]
    is_unknown: bool
    descriptors: list[str]
    environment: str | None
    mood: str | None
    note: str | None
    prediction_id: str | None
    superseded_by: str | None
    created_at: str


class AnnotationResult(BaseModel):
    annotation: AnnotationOut
    memory_version: int
    exemplars_added: int
    exemplars_retracted: int
    # label stored, but the recording has no embedding yet, so memory has not changed
    memory_pending: bool = False
    created_label_ids: list[str]
    rescored_changes: list[dict[str, Any]]
    fused_top: list[dict[str, Any]]


class MemoryOverview(BaseModel):
    memory_version: int
    model_version_id: str | None
    exemplars: int
    annotations: int
    unknown_annotations: int
    custom_labels: int
    labels: list[dict[str, Any]]
    label_names: dict[str, str]


class EchoLine(BaseModel):
    template: str
    text: str
    tags: list[Literal["model", "memory", "imagination"]]
    event_ids: list[str]
