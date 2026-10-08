"""Contract test for the AudioModel adapter with a deterministic fake (tests only)."""

from __future__ import annotations

import numpy as np

from tests.fixtures import synth
from unheard.models.contracts import (
    AudioInferenceInput,
    AudioModel,
    Embedding,
    InferenceResult,
    LabelScore,
    ModelInfo,
)


class FakeAudioModel:
    """Deterministic stand-in: 'label' from RMS, embedding from a fixed projection."""

    def info(self) -> ModelInfo:
        return ModelInfo(model_id="fake", model_version="0", embedding_dim=8, label_space="fake-2")

    def infer(self, inp: AudioInferenceInput) -> InferenceResult:
        rms = float(np.sqrt(np.mean(inp.samples**2)))
        vec = np.full(8, rms, dtype=np.float32)
        vec /= np.linalg.norm(vec) or 1.0
        return InferenceResult(
            status="ok",
            model=self.info(),
            predictions=[
                LabelScore("loud", min(1.0, rms * 4)),
                LabelScore("quiet", 1 - min(1.0, rms * 4)),
            ],
            embedding=Embedding(vector=vec),
        )


def test_fake_model_satisfies_protocol_and_is_deterministic() -> None:
    model = FakeAudioModel()
    assert isinstance(model, AudioModel)
    x = synth.sine(440, 48000, 1.0)
    inp = AudioInferenceInput(recording_id="r", samples=x, sample_rate=48000, duration_s=1.0)
    a, b = model.infer(inp), model.infer(inp)
    assert a.to_json() == b.to_json()
    assert a.status == "ok" and a.embedding is not None and a.embedding.vector.size == 8


def test_not_run_result_has_no_predictions() -> None:
    j = InferenceResult.not_run().to_json()
    assert j == {
        "status": "not_run",
        "model_id": None,
        "model_version": None,
        "predictions": [],
        "embedding": None,
        "error": None,
    }
