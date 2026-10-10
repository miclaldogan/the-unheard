"""Response models for /api/narrative (contract m5.1, docs/contracts/M5-NARRATIVE-API.md). Extra fields are allowed so the
contract can grow additively; the frontend must ignore unknown fields."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Provenance = Literal[
    "model", "user_confirmed", "personal_memory", "measurement", "system", "imagination"
]


class _M(BaseModel):
    model_config = ConfigDict(extra="allow")


class RefOut(_M):
    type: Literal[
        "recording",
        "annotation",
        "label",
        "prediction",
        "composition",
        "atlas_edge",
        "mission",
        "measurement",
    ]
    id: str
    label: str | None = None
    provenance: Provenance


class FactOut(_M):
    handle: str
    statement: str
    provenance: Provenance
    ref: RefOut | None = None


class LineOut(_M):
    text: str
    kind: Literal["grounded", "imagination"]
    provenance: list[Provenance]
    cites: list[str]


class MomentOut(_M):
    kind: Literal[
        "awaiting_sound",
        "first_sound",
        "teaching",
        "correction",
        "unknown",
        "relationship",
        "ready_to_compose",
        "composition",
        "ending",
    ]
    key: str
    act: str
    occurred_at: str


class GenerationOut(_M):
    status: Literal["ready", "pending", "fallback"]
    latency_ms: float | None = None
    attempts: int = 0
    fallback_reason: (
        Literal[
            "disabled",
            "unavailable",
            "timeout",
            "invalid_output",
            "invalid_json",
            "busy",
            "no_model",
        ]
        | None
    ) = None


class UtteranceOut(_M):
    id: str
    revision: int
    moment: MomentOut
    lines: list[LineOut]
    facts: list[FactOut]
    source: Literal["gemma", "template"]
    model: str | None = None
    generation: GenerationOut
    created_at: str


class CurrentOut(_M):
    contract_version: str
    utterance: UtteranceOut
    available_actions: list[str]


class EchoOut(_M):
    contract_version: str
    utterances: list[UtteranceOut]


class ProgressOut(_M):
    current: int
    target: int


class CriterionOut(_M):
    id: str
    text: str
    met: bool
    evidence: list[RefOut] = []


class ActOut(_M):
    id: str
    title: str
    status: Literal["locked", "active", "complete"]
    progress: ProgressOut
    criteria: list[CriterionOut]


class MilestoneOut(_M):
    id: str
    title: str
    achieved: bool
    achieved_at: str | None = None
    optional: bool
    evidence: list[RefOut] = []


class StateOut(_M):
    contract_version: str
    derived_at: str
    act: Literal["prologue", "act_1", "act_2", "act_3", "ending"]
    phase: Literal[
        "awaiting_sound", "first_hearing", "teaching", "ready_to_compose", "composing", "remembered"
    ]
    ending_unlocked: bool
    acts: list[ActOut]
    milestones: list[MilestoneOut]
    counts: dict[str, int]
    gemma: dict[str, Any]


class WordingOut(_M):
    text: str
    source: Literal["gemma", "template"]


class MissionOut(_M):
    id: str
    type: Literal[
        "record_first",
        "gather_three",
        "resolve_unknown",
        "second_example",
        "novel_sound",
        "repeat_not_machine",
        "find_tonal",
    ]
    title: str
    objective: str
    reason: str
    evidence: list[RefOut]
    completion: dict[str, str]
    safe_fallback: str
    safety: str
    status: Literal["available", "active", "completed", "expired"]
    wording: WordingOut
    activated_at: str | None = None
    completed_at: str | None = None
    progress: ProgressOut | None = None


class MissionsOut(_M):
    contract_version: str
    max_active: int
    active: list[MissionOut]
    candidates: list[MissionOut]
    completed: list[MissionOut]
    selection: dict[str, Any]


class TimelineOut(_M):
    contract_version: str
    entries: list[dict[str, Any]]
    next_before: str | None = None


class SettingsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    gemma_enabled: bool = Field(
        description="Allow Gemma to write ECHO-0's lines (templates are used when off)"
    )


class SettingsOut(_M):
    contract_version: str
    gemma_enabled: bool


class ModelStatusOut(_M):
    contract_version: str
    runtime: str
    base_url: str
    enabled: bool
    available: bool
    status: Literal["ready", "loading", "unavailable", "disabled", "no_model"]
    model: str | None = None
    installed: list[str]
    license: str | None = None
    limits: dict[str, Any]
    stats: dict[str, Any]
