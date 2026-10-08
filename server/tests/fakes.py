"""Deterministic test double for the CLAP adapter (no torch, no weights).

Embeddings are a seeded random projection of a 32-band log power spectrum, so signals with
similar spectra land close together and different ones far apart. Text embeddings are
seeded per prompt so "The sound of birds" is stable across runs.
"""

from __future__ import annotations

import hashlib

import numpy as np
from numpy.typing import NDArray

from unheard.models.clap import ClapAudioModel, WindowEmbedding, plan_windows
from unheard.storage.vectors import l2_normalize

DIM = 32
_PROJ = np.random.default_rng(1234).standard_normal((32, DIM)).astype(np.float32)


def _spectrum_vec(x: NDArray[np.floating], sr: int) -> NDArray[np.float32]:
    x = np.asarray(x, dtype=np.float64)
    if x.size < 2048:
        x = np.pad(x, (0, 2048 - x.size))
    spec = np.abs(np.fft.rfft(x[: min(x.size, sr * 10)])) ** 2
    edges = np.linspace(0, spec.size, 33).astype(int)
    bands = np.array(
        [spec[a:b].mean() if b > a else 0.0 for a, b in zip(edges[:-1], edges[1:], strict=True)]
    )
    # log band energies, NOT standardised: flat spectra (noise) share a direction, tones
    # with different frequencies point elsewhere. Level changes only shift it slightly.
    feat = np.log10(bands + 1e-12)
    feat = (
        np.clip(feat - feat.max(), -6.0, 0.0) + 3.0
    )  # flat spectrum → all +3; tone → one +3, rest −3
    return l2_normalize(feat @ _PROJ)


class FakeClap(ClapAudioModel):
    def __init__(self) -> None:
        super().__init__(name="fake/clap", device="cpu", allow_download=False)
        self.embedding_dim = DIM
        self.revision = "fake-rev-1"
        self.load_seconds = 0.0
        self._model = object()  # marks "loaded"
        self._processor = object()
        self.text_calls = 0
        self.audio_calls = 0

    def load(self) -> None:  # pragma: no cover
        pass

    def embed_text(self, prompts: list[str]) -> NDArray[np.float32]:
        self.text_calls += 1
        out = np.zeros((len(prompts), DIM), dtype=np.float32)
        for i, p in enumerate(prompts):
            seed = int.from_bytes(hashlib.sha256(p.encode()).digest()[:4], "big")
            out[i] = l2_normalize(np.random.default_rng(seed).standard_normal(DIM))
        return out

    def embed_windows(
        self, samples: NDArray[np.floating], sample_rate: int
    ) -> list[WindowEmbedding]:
        self.audio_calls += 1
        x = np.asarray(samples, dtype=np.float32)
        plan = plan_windows(x.size / sample_rate)
        return [
            WindowEmbedding(
                i, s, e, _spectrum_vec(x[int(s * sample_rate) : int(e * sample_rate)], sample_rate)
            )
            for i, (s, e) in enumerate(plan)
        ]


def install_fake(services) -> FakeClap:  # type: ignore[no-untyped-def]
    """Inject the fake into a ModelManager built with model_name != 'none'."""
    fake = FakeClap()
    services.models._model = fake
    services.models._status = "ready"
    return fake
