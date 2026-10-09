"""Acoustic signature generator v1 — scientific features → compact visual parameters.

Pure function of (feature summary, feature arrays, semantic state, seed). The browser turns
these parameters into geometry; this module never touches audio or embeddings except to
derive a small, documented set of numbers.

Visual grammar v1 (doc 05 §3, implemented here; every mapping is artistic interpretation of a
measured quantity, documented in docs/visual-grammar.md):

| param              | source (measured)                     | mapping |
|--------------------|---------------------------------------|---------|
| ring[128]          | RMS envelope (dBFS, resampled)        | normalised −60…0 dBFS → 0…1 (radius profile) |
| sharpness          | spectral centroid median (Hz)         | log scale 150 Hz…8 kHz → 0…1 (spike angle / crispness) |
| symmetry_order     | 1 − spectral flatness median          | 2 + round(6·tonality) (fold symmetry) |
| jitter             | spectral flatness median              | flatness → 0…1 radial jitter amplitude (noisy = irregular) |
| fragmentation      | spectral flux median / max            | 0…1 → stroke gaps (dash) |
| ticks[]            | onset times (s) / duration            | one radial tick per onset at its angle |
| bands[32]          | log-mel band means (dB)               | normalised inner texture rings |
| brightness_curve   | centroid series (32 pts)              | hue-light modulation around the ring during playback |
| scale              | duration (s)                          | 0.6…1.0 overall scale (3 s…30 s, log) |
| energy             | RMS dBFS                              | −60…−10 → 0…1 stroke weight |
| semantic.hue       | top fused label / confirmed label     | label.hue_seed (the ONLY label-driven geometry input is none: hue is styling) |
| semantic.state     | annotation / novelty                  | confirmed · hypothesis · uncertain · unknown |
| semantic.resolve   | nearest-exemplar cosine, margin       | 0…1 "resolution" (outline solidity) |

Geometry params exclude everything under ``semantic`` so ``geometry_hash`` is label-independent.
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any

import numpy as np
from numpy.typing import NDArray

GENERATOR_VERSION = 1
RING_POINTS = 128
BAND_POINTS = 32
CURVE_POINTS = 32
MAX_TICKS = 96


def _finite(x: float, default: float = 0.0) -> float:
    return float(x) if x is not None and math.isfinite(float(x)) else default


def _clamp01(x: float) -> float:
    return float(min(1.0, max(0.0, x)))


def _resample(v: NDArray[np.floating] | list[float], n: int) -> list[float]:
    a = np.asarray(v, dtype=np.float64).ravel()
    a = np.where(np.isfinite(a), a, 0.0)
    if a.size == 0:
        return [0.0] * n
    if a.size == 1:
        return [float(a[0])] * n
    x_old = np.linspace(0.0, 1.0, a.size)
    x_new = np.linspace(0.0, 1.0, n)
    return [float(y) for y in np.interp(x_new, x_old, a)]


def _norm_db(values: list[float], lo: float, hi: float) -> list[float]:
    return [_clamp01((v - lo) / (hi - lo)) for v in values]


def seed_from_hash(content_hash: str, generator_version: int = GENERATOR_VERSION) -> int:
    """Stable 32-bit seed: first 8 hex chars of sha256(content_hash || version)."""
    h = hashlib.sha256(f"{content_hash}:{generator_version}".encode()).hexdigest()
    return int(h[:8], 16)


def geometry_params(summary: dict[str, Any], arrays: dict[str, Any]) -> dict[str, Any]:
    """Label-independent geometry from the DSP summary and arrays. All outputs bounded."""
    duration = max(0.01, _finite(summary.get("duration_s", 0.0), 0.01))
    rms_db = _finite(summary.get("rms_dbfs", -60.0), -60.0)
    centroid = max(
        1.0, _finite(summary.get("spectral_centroid_hz", {}).get("median", 1000.0), 1000.0)
    )
    flatness = _clamp01(_finite(summary.get("spectral_flatness", {}).get("median", 0.5), 0.5))
    flux = summary.get("spectral_flux", {})
    flux_med = _finite(flux.get("median", 0.0))
    flux_max = max(1e-9, _finite(flux.get("max", 1.0), 1.0))
    onset_times = [
        t
        for t in summary.get("onset_times_s", [])
        if isinstance(t, int | float) and math.isfinite(t)
    ]

    env = _norm_db(_resample(arrays.get("rms_envelope_db", [rms_db]), RING_POINTS), -60.0, 0.0)
    log_mel = np.asarray(arrays.get("log_mel_db", np.zeros((1, 1))), dtype=np.float64)
    if log_mel.ndim == 2 and log_mel.size:
        band_means = np.where(np.isfinite(log_mel), log_mel, -100.0).mean(axis=1)
    else:
        band_means = np.full(1, -100.0)
    bands = _norm_db(_resample(band_means, BAND_POINTS), -100.0, 0.0)
    centroid_series = np.asarray(arrays.get("centroid_hz", [centroid]), dtype=np.float64)
    centroid_series = np.where(
        np.isfinite(centroid_series) & (centroid_series > 0), centroid_series, centroid
    )
    curve = [
        _clamp01(
            (math.log10(max(1.0, c)) - math.log10(150.0)) / (math.log10(8000.0) - math.log10(150.0))
        )
        for c in _resample(centroid_series, CURVE_POINTS)
    ]

    sharpness = _clamp01(
        (math.log10(centroid) - math.log10(150.0)) / (math.log10(8000.0) - math.log10(150.0))
    )
    tonality = 1.0 - flatness
    symmetry_order = int(2 + round(6 * tonality))
    fragmentation = _clamp01(flux_med / flux_max) if flux_max > 0 else 0.0
    scale = _clamp01(
        (math.log10(max(3.0, min(30.0, duration))) - math.log10(3.0))
        / (math.log10(30.0) - math.log10(3.0))
    )
    energy = _clamp01((rms_db + 60.0) / 50.0)
    ticks = [_clamp01(t / duration) for t in onset_times[:MAX_TICKS]]

    return {
        "ring": [round(v, 4) for v in env],
        "bands": [round(v, 4) for v in bands],
        "brightness_curve": [round(v, 4) for v in curve],
        "ticks": [round(t, 4) for t in ticks],
        "sharpness": round(sharpness, 4),
        "symmetry_order": symmetry_order,
        "jitter": round(flatness, 4),
        "fragmentation": round(fragmentation, 4),
        "scale": round(0.6 + 0.4 * scale, 4),
        "energy": round(energy, 4),
        "duration_s": round(duration, 3),
        "onset_density_per_s": round(_finite(summary.get("onset_density_per_s", 0.0)), 4),
    }


def animation_params(arrays: dict[str, Any], summary: dict[str, Any]) -> dict[str, Any]:
    """Precomputed timelines for playback-synchronised animation (seconds → values)."""
    duration = max(0.01, _finite(summary.get("duration_s", 0.0), 0.01))
    env = _norm_db(_resample(arrays.get("rms_envelope_db", [-60.0]), 256), -60.0, 0.0)
    flux = np.asarray(arrays.get("flux", [0.0]), dtype=np.float64)
    flux = np.where(np.isfinite(flux), flux, 0.0)
    fmax = float(flux.max()) if flux.size and flux.max() > 0 else 1.0
    flux_tl = [round(_clamp01(v / fmax), 4) for v in _resample(flux, 128)]
    onsets = [
        round(float(t), 3)
        for t in summary.get("onset_times_s", [])
        if isinstance(t, int | float) and math.isfinite(t)
    ][:MAX_TICKS]
    return {
        "duration_s": round(duration, 3),
        "envelope": [round(v, 4) for v in env],
        "flux": flux_tl,
        "onsets_s": onsets,
    }


def semantic_params(
    *,
    label_name: str | None,
    label_hue: int | None,
    state: str,
    resolution: float,
    confirmed_labels: list[str],
    descriptors: list[str],
    environment: str | None,
    mood: str | None,
    novelty: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "label": label_name,
        "hue": int(label_hue) if label_hue is not None else None,
        "state": state,  # unknown | uncertain | hypothesis | confirmed
        "resolution": round(_clamp01(resolution), 4),
        "confirmed_labels": confirmed_labels,
        "descriptors": descriptors,
        "environment": environment,
        "mood": mood,
        "why": None
        if novelty is None
        else {
            "novel": bool(novelty.get("novel")),
            "nearest_exemplar_similarity": novelty.get("nearest_exemplar_similarity"),
            "fused_margin": novelty.get("fused_margin"),
            "base_entropy_normalised": novelty.get("base_entropy_normalised"),
            "disagreement": bool(novelty.get("disagreement")),
        },
    }


def geometry_hash(geometry: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(geometry, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def build_params(
    *,
    content_hash: str,
    summary: dict[str, Any],
    arrays: dict[str, Any],
    semantic: dict[str, Any],
    dsp_version: int,
) -> tuple[dict[str, Any], int, str]:
    seed = seed_from_hash(content_hash)
    geom = geometry_params(summary, arrays)
    ghash = geometry_hash(geom)
    params = {
        "generator_version": GENERATOR_VERSION,
        "seed": seed,
        "dsp_version": dsp_version,
        "geometry": geom,
        "animation": animation_params(arrays, summary),
        "semantic": semantic,
        "geometry_hash": ghash,
    }
    return params, seed, ghash
