"""Shared builders for M4 tests (synthetic sources with M1 feature arrays)."""

from __future__ import annotations

import hashlib

import numpy as np
from numpy.typing import NDArray

from tests.fixtures import synth
from unheard.dsp.features import extract_features
from unheard.music.engine import SourceInput

SR = 48_000


def make_source(x: NDArray[np.float64]) -> SourceInput:
    key = hashlib.sha256(x.astype("<f4").tobytes()).hexdigest()
    return SourceInput(key, x, extract_features(x, SR).arrays)


def tone_melody(duration: float = 6.0) -> NDArray[np.float64]:
    """Three decaying notes (220, 262, 330 Hz) repeated: unambiguously pitched."""
    n = int(duration * SR)
    out = np.zeros(n)
    t_note = np.arange(int(0.6 * SR)) / SR
    freqs = [220.0, 262.0, 330.0]
    pos, i = 0, 0
    while pos + t_note.size < n:
        f = freqs[i % 3]
        out[pos : pos + t_note.size] += 0.4 * np.sin(2 * np.pi * f * t_note) * np.exp(-2.0 * t_note)
        pos += int(0.7 * SR)
        i += 1
    return out


def steady_noise(duration: float = 6.0, seed: int = 3) -> NDArray[np.float64]:
    rng = np.random.default_rng(seed)
    x = rng.standard_normal(int(duration * SR))
    x = np.convolve(x, np.ones(16) / 16, mode="same")
    return 0.25 * x / np.max(np.abs(x))


def three_sources() -> list[SourceInput]:
    return [
        make_source(steady_noise()),
        make_source(synth.click_train(3.0, SR, 6.0)),
        make_source(tone_melody()),
    ]
