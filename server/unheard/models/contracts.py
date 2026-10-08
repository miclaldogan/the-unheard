"""Contracts for the audio-model adapter (``AudioModel``), consumed in M2.

Nothing here runs a model. Production code in M1 only reports
``InferenceResult(status="not_run")`` so the API can distinguish "features extracted" from
"model inference not yet available" without fabricating predictions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol, runtime_checkable

import numpy as np
from numpy.typing import NDArray

InferenceStatus = Literal["not_run", "ok", "failed", "unavailable"]


@dataclass(frozen=True)
class AudioInferenceInput:
    """Canonical audio handed to a model: mono float32/64 PCM at ``sample_rate``.

    Adapters are responsible for any model-specific resampling (e.g. 16 kHz for YAMNet)
    and windowing (10 s windows, 50 % hop, doc 03 §1). ``recording_id`` is for provenance.
    """

    recording_id: str
    samples: NDArray[np.float64]
    sample_rate: int
    duration_s: float


@dataclass(frozen=True)
class ModelInfo:
    model_id: str
    model_version: str
    license_note: str | None = None
    sha256: str | None = None
    input_sample_rate: int | None = None
    embedding_dim: int | None = None
    label_space: str | None = None  # e.g. "audioset-521", "open-vocabulary"


@dataclass(frozen=True)
class LabelScore:
    label: str
    score: float  # independent per label (not softmax), in [0, 1]


@dataclass(frozen=True)
class Embedding:
    vector: NDArray[np.float32]  # L2-normalised
    window_idx: int | None = None


@dataclass(frozen=True)
class ModelError:
    code: str
    message: str
    retryable: bool = False


@dataclass(frozen=True)
class InferenceResult:
    status: InferenceStatus
    model: ModelInfo | None = None
    predictions: list[LabelScore] = field(default_factory=list)
    embedding: Embedding | None = None
    error: ModelError | None = None

    @staticmethod
    def not_run() -> InferenceResult:
        return InferenceResult(status="not_run")

    def to_json(self) -> dict[str, object]:
        return {
            "status": self.status,
            "model_id": self.model.model_id if self.model else None,
            "model_version": self.model.model_version if self.model else None,
            "predictions": [{"label": p.label, "score": p.score} for p in self.predictions],
            "embedding": None
            if self.embedding is None
            else {"dim": int(self.embedding.vector.size), "window_idx": self.embedding.window_idx},
            "error": None
            if self.error is None
            else {
                "code": self.error.code,
                "message": self.error.message,
                "retryable": self.error.retryable,
            },
        }


@runtime_checkable
class AudioModel(Protocol):
    """Adapter boundary (ADR-004). Implementations must be deterministic for a fixed input."""

    def info(self) -> ModelInfo: ...

    def infer(self, inp: AudioInferenceInput) -> InferenceResult: ...
