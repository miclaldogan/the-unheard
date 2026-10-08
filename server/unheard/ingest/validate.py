"""Signal-level validation and quality flags, measured on the decoded signal.

Rejections (raise) vs flags (returned in ``quality``): doc 03 §1 "Quality assessment".
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from numpy.typing import NDArray

from unheard.errors import (
    AudioBadSampleRate,
    AudioEmpty,
    AudioInvalidSamples,
    AudioSilent,
    AudioTooLong,
    AudioTooShort,
)


@dataclass(frozen=True)
class Limits:
    min_duration_s: float
    max_duration_s: float
    min_source_sample_rate: int
    max_source_sample_rate: int
    silence_dbfs: float
    clipping_peak: float
    clipping_flag_ratio: float


def _dbfs(x: float) -> float:
    return float(20.0 * np.log10(max(x, 1e-12)))


def sanitize(samples: NDArray[np.float64]) -> tuple[NDArray[np.float64], int]:
    """Replace NaN/Inf with 0 and return the count replaced (reported as a flag)."""
    bad = ~np.isfinite(samples)
    n_bad = int(bad.sum())
    if n_bad:
        samples = samples.copy()
        samples[bad] = 0.0
    return samples, n_bad


def validate_decoded(
    samples: NDArray[np.float64],
    sample_rate: int,
    source_sample_rate: int,
    source_channels: int,
    limits: Limits,
) -> tuple[NDArray[np.float64], dict[str, Any]]:
    """Validate and return ``(clean_samples, quality)``.

    Raises an ``AudioRejected`` subclass for hard failures.
    """
    if samples.size == 0:
        raise AudioEmpty("decoded audio contains no samples")
    if not (limits.min_source_sample_rate <= source_sample_rate <= limits.max_source_sample_rate):
        raise AudioBadSampleRate(
            f"source sample rate {source_sample_rate} Hz is outside "
            f"[{limits.min_source_sample_rate}, {limits.max_source_sample_rate}]"
        )
    if source_channels < 1 or source_channels > 8:
        raise AudioBadSampleRate(f"unsupported channel count {source_channels}")

    samples, n_bad = sanitize(samples)
    if n_bad > samples.size * 0.01:
        raise AudioInvalidSamples(f"{n_bad} non-finite samples ({n_bad / samples.size:.1%})")

    duration = samples.size / sample_rate
    if duration < limits.min_duration_s:
        raise AudioTooShort(
            f"duration {duration:.2f} s is below the minimum of {limits.min_duration_s} s",
            extra={"duration_s": duration},
        )
    if duration > limits.max_duration_s:
        raise AudioTooLong(
            f"duration {duration:.2f} s exceeds the maximum of {limits.max_duration_s} s",
            extra={"duration_s": duration},
        )

    peak = float(np.max(np.abs(samples)))
    rms = float(np.sqrt(np.mean(samples * samples)))
    rms_dbfs = _dbfs(rms)
    if rms_dbfs < limits.silence_dbfs:
        raise AudioSilent(
            f"RMS {rms_dbfs:.1f} dBFS is below the silence threshold {limits.silence_dbfs} dBFS",
            extra={"rms_dbfs": rms_dbfs},
        )

    clipped = int(np.count_nonzero(np.abs(samples) >= limits.clipping_peak))
    clip_ratio = clipped / samples.size
    dc = float(np.mean(samples))

    quality = {
        "peak": peak,
        "peak_dbfs": _dbfs(peak),
        "rms_dbfs": rms_dbfs,
        "dc_offset": dc,
        "clipped_samples": clipped,
        "clipping_ratio": clip_ratio,
        "non_finite_samples_replaced": n_bad,
        "flags": sorted(
            f
            for f, on in {
                "clipping": clip_ratio > limits.clipping_flag_ratio,
                "dc_offset": abs(dc) > 0.05,
                "quiet": rms_dbfs < -40.0,
                "non_finite_samples": n_bad > 0,
            }.items()
            if on
        ),
    }
    return samples, quality
