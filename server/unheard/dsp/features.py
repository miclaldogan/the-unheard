"""Feature extraction v1.

All features are computed on the *canonical* signal (mono, 48 kHz, float64, no gain
change). Parameters are fixed per ``DSP_VERSION``; same input + version ⇒ identical output.

Feature definitions (``sr`` = sample rate, ``M[k,t]`` = STFT magnitude, ``P = M²``,
``f_k`` = bin centre frequency):

Time domain
* duration_s = N / sr
* peak = max |x|; peak_dbfs = 20·log10(peak)
* rms = sqrt(mean x²); rms_dbfs = 20·log10(rms)
* clipping_ratio = #{|x| ≥ 0.99} / N
* zero_crossing_rate = #{sign(x[n]) ≠ sign(x[n-1])} / (N-1)   [crossings per sample]
  (for a pure tone at f Hz this is 2f/sr)
* rms_envelope_db[t]: RMS over the same frames as the STFT (n_fft window), in dBFS
* waveform summary: the signal split into ≤ WAVEFORM_BUCKETS equal buckets; per bucket
  min, max and rms (for drawing; not used for inference)

Spectral (per frame, from STFT n_fft=2048, hop=512, Hann; reported as mean/median/std
over *active* frames, i.e. frames whose energy is above -80 dBFS)
* centroid_hz[t]   = Σ f_k·M[k,t] / Σ M[k,t]
* bandwidth_hz[t]  = sqrt( Σ M[k,t]·(f_k − centroid)² / Σ M[k,t] )
* rolloff_hz[t]    = smallest f_k such that Σ_{j≤k} P[j,t] ≥ 0.85 · Σ_j P[j,t]
* flatness[t]      = exp(mean_k log(P[k,t]+ε)) / (mean_k P[k,t] + ε), ε = 1e-10  (0 tone … 1 noise)
* flux[t]          = sqrt( Σ_k max(0, M[k,t] − M[k,t−1])² )   (half-wave rectified L2; flux[0]=0)

Mel
* log_mel[m,t] = 10·log10(max(Σ_k H[m,k]·P_mel[k,t], 1e-10)) with a 64-band HTK mel bank over
  20 Hz…sr/2, computed from a second STFT with 25 ms window / 10 ms hop / n_fft 2048.
* onset_strength[t] = mean_m max(0, log_mel[m,t] − log_mel[m,t−1])  (spectral-flux novelty in dB)
* onsets: peaks of onset_strength that are local maxima over ±3 frames, exceed the global
  mean + 2·std AND exceed the local median (±0.5 s) by ≥ 3 dB, with ≥ 50 ms between onsets.
  onset_density = onsets / duration (events per second).

Edge cases: empty signal raises; all-zero frames give centroid/bandwidth/rolloff = 0 and
flatness = 1 (ε/ε) and are excluded from "active" statistics; NaN/Inf must already be
removed by ingest (asserted here).
"""

from __future__ import annotations

import hashlib
import io
import json
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from numpy.typing import NDArray

from unheard.dsp.stft import (
    fft_frequencies,
    frame_signal,
    frame_times,
    mel_filterbank,
    mel_frequencies,
    power_to_db,
    stft_magnitude,
)

DSP_VERSION = 1

# Parameters (part of the version contract; changing any of them bumps DSP_VERSION)
STFT_N_FFT = 2048
STFT_HOP = 512
MEL_N_FFT = 2048
MEL_WIN_MS = 25.0
MEL_HOP_MS = 10.0
MEL_BANDS = 64
MEL_FMIN_HZ = 20.0
ROLLOFF_FRACTION = 0.85
CLIP_PEAK = 0.99
ACTIVE_FRAME_DBFS = -80.0
ONSET_MIN_GAP_S = 0.05
ONSET_PEAK_HALF_WINDOW = 3
ONSET_MIN_DB = 3.0
ONSET_LOCAL_MEDIAN_S = 0.5
WAVEFORM_BUCKETS = 1200
STFT_VIEW_BINS = 256  # linear spectrogram stored pooled to this many bins
EPS = 1e-10


@dataclass
class FeatureResult:
    version: int
    sample_rate: int
    summary: dict[str, Any]  # JSON-serialisable scalars + parameters
    arrays: dict[str, NDArray[Any]] = field(default_factory=dict)  # stored as .npz

    def to_npz_bytes(self) -> bytes:
        buf = io.BytesIO()
        np.savez(buf, **self.arrays)  # type: ignore[arg-type]  # uncompressed: deterministic bytes
        return buf.getvalue()

    def summary_hash(self) -> str:
        return hashlib.sha256(
            json.dumps(self.summary, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()


def _stats(v: NDArray[np.float64], mask: NDArray[np.bool_] | None = None) -> dict[str, float]:
    if mask is not None:
        v = v[mask]
    if v.size == 0:
        return {"mean": 0.0, "median": 0.0, "std": 0.0, "min": 0.0, "max": 0.0}
    return {
        "mean": float(np.mean(v)),
        "median": float(np.median(v)),
        "std": float(np.std(v)),
        "min": float(np.min(v)),
        "max": float(np.max(v)),
    }


def _dbfs(x: float) -> float:
    return float(20.0 * np.log10(max(x, 1e-12)))


def waveform_summary(x: NDArray[np.float64], buckets: int) -> dict[str, NDArray[np.float64]]:
    n = x.size
    b = min(buckets, n)
    edges = np.linspace(0, n, b + 1).astype(np.int64)
    mins = np.empty(b)
    maxs = np.empty(b)
    rms = np.empty(b)
    for i in range(b):
        seg = x[edges[i] : edges[i + 1]]
        if seg.size == 0:
            mins[i] = maxs[i] = rms[i] = 0.0
            continue
        mins[i] = seg.min()
        maxs[i] = seg.max()
        rms[i] = np.sqrt(np.mean(seg * seg))
    return {"wave_min": mins, "wave_max": maxs, "wave_rms": rms}


def zero_crossing_rate(x: NDArray[np.float64]) -> float:
    if x.size < 2:
        return 0.0
    s = np.signbit(x)
    return float(np.count_nonzero(s[1:] != s[:-1]) / (x.size - 1))


def spectral_frame_features(
    mag: NDArray[np.float64], freqs: NDArray[np.float64]
) -> dict[str, NDArray[np.float64]]:
    power = mag * mag
    mag_sum = mag.sum(axis=0)
    pow_sum = power.sum(axis=0)
    safe_mag = np.where(mag_sum > 0, mag_sum, 1.0)
    centroid = (freqs[:, None] * mag).sum(axis=0) / safe_mag
    centroid = np.where(mag_sum > 0, centroid, 0.0)
    dev = (freqs[:, None] - centroid[None, :]) ** 2
    bandwidth = np.sqrt((dev * mag).sum(axis=0) / safe_mag)
    bandwidth = np.where(mag_sum > 0, bandwidth, 0.0)

    cum = np.cumsum(power, axis=0)
    threshold = ROLLOFF_FRACTION * pow_sum
    # first bin where cumulative power reaches the threshold
    reached = cum >= threshold[None, :]
    idx = np.argmax(reached, axis=0)
    rolloff = np.where(pow_sum > 0, freqs[idx], 0.0)

    flatness = np.exp(np.mean(np.log(power + EPS), axis=0)) / (np.mean(power, axis=0) + EPS)

    diff = np.diff(mag, axis=1)
    flux = np.concatenate([[0.0], np.sqrt((np.maximum(diff, 0.0) ** 2).sum(axis=0))])

    return {
        "centroid_hz": centroid,
        "bandwidth_hz": bandwidth,
        "rolloff_hz": rolloff,
        "flatness": np.clip(flatness, 0.0, 1.0),
        "flux": flux,
    }


def onset_strength(log_mel_db: NDArray[np.float64]) -> NDArray[np.float64]:
    d = np.diff(log_mel_db, axis=1)
    strength = np.maximum(d, 0.0).mean(axis=0)
    return np.concatenate([[0.0], strength])


def local_median(x: NDArray[np.float64], half: int) -> NDArray[np.float64]:
    out = np.empty_like(x)
    n = x.size
    for i in range(n):
        out[i] = np.median(x[max(0, i - half) : min(n, i + half + 1)])
    return out


def pick_onsets(strength: NDArray[np.float64], sr: int, hop: int) -> NDArray[np.int64]:
    n = strength.size
    if n == 0:
        return np.zeros(0, dtype=np.int64)
    # Stationary noise has a non-zero, roughly constant novelty; a peak must rise above the
    # *local* median by an absolute margin (ONSET_MIN_DB) and above the global mean + 2·std.
    half = max(1, int(round(ONSET_LOCAL_MEDIAN_S * sr / hop)))
    baseline = local_median(strength, half)
    global_thr = float(strength.mean() + 2.0 * strength.std())
    w = ONSET_PEAK_HALF_WINDOW
    min_gap = int(round(ONSET_MIN_GAP_S * sr / hop))
    peaks: list[int] = []
    last = -(10**9)
    for t in range(n):
        v = strength[t]
        if v < global_thr or v - baseline[t] < ONSET_MIN_DB:
            continue
        lo, hi = max(0, t - w), min(n, t + w + 1)
        if v < strength[lo:hi].max():
            continue
        if t - last < min_gap:
            continue
        peaks.append(t)
        last = t
    return np.asarray(peaks, dtype=np.int64)


def pool_bins(power: NDArray[np.float64], n_out: int) -> NDArray[np.float64]:
    """Mean-pool the frequency axis (n_bins, T) down to (n_out, T)."""
    n_bins = power.shape[0]
    if n_bins <= n_out:
        return power
    edges = np.linspace(0, n_bins, n_out + 1).astype(np.int64)
    out = np.empty((n_out, power.shape[1]), dtype=np.float64)
    for i in range(n_out):
        out[i] = power[edges[i] : edges[i + 1]].mean(axis=0)
    return out


def extract_features(x: NDArray[np.float64], sr: int) -> FeatureResult:
    x = np.asarray(x, dtype=np.float64)
    if x.ndim != 1:
        raise ValueError("expected a mono 1-D signal")
    if x.size == 0:
        raise ValueError("empty signal")
    if not np.all(np.isfinite(x)):
        raise ValueError("signal contains NaN/Inf; sanitise before extraction")

    n = x.size
    duration = n / sr
    peak = float(np.max(np.abs(x)))
    rms = float(np.sqrt(np.mean(x * x)))
    clipping_ratio = float(np.count_nonzero(np.abs(x) >= CLIP_PEAK) / n)
    zcr = zero_crossing_rate(x)

    # --- STFT for spectral statistics
    mag = stft_magnitude(x, n_fft=STFT_N_FFT, hop=STFT_HOP)
    freqs = fft_frequencies(sr, STFT_N_FFT)
    times = frame_times(mag.shape[1], sr, STFT_HOP)
    frames = frame_signal(x, n_fft=STFT_N_FFT, hop=STFT_HOP)
    rms_env = np.sqrt(np.mean(frames * frames, axis=1))
    rms_env_db = 20.0 * np.log10(np.maximum(rms_env, 1e-12))
    active = rms_env_db > ACTIVE_FRAME_DBFS
    spec = spectral_frame_features(mag, freqs)
    stft_view_db = power_to_db(pool_bins(mag * mag, STFT_VIEW_BINS))

    # --- log-mel on a 25 ms / 10 ms grid
    mel_win = int(round(MEL_WIN_MS * sr / 1000.0))
    mel_hop = int(round(MEL_HOP_MS * sr / 1000.0))
    mel_mag = stft_magnitude(x, n_fft=MEL_N_FFT, hop=mel_hop, win_length=mel_win)
    fb = mel_filterbank(sr, MEL_N_FFT, MEL_BANDS, MEL_FMIN_HZ, sr / 2)
    mel_power = fb @ (mel_mag * mel_mag)
    log_mel = power_to_db(mel_power)
    mel_times = frame_times(log_mel.shape[1], sr, mel_hop)
    strength = onset_strength(log_mel)
    onset_idx = pick_onsets(strength, sr, mel_hop)
    onset_times = mel_times[onset_idx]

    wave = waveform_summary(x, WAVEFORM_BUCKETS)

    summary: dict[str, Any] = {
        "dsp_version": DSP_VERSION,
        "sample_rate": sr,
        "n_samples": int(n),
        "duration_s": duration,
        "peak": peak,
        "peak_dbfs": _dbfs(peak),
        "rms": rms,
        "rms_dbfs": _dbfs(rms),
        "clipping_ratio": clipping_ratio,
        "zero_crossing_rate": zcr,
        "zero_crossings_per_s": zcr * sr,
        "active_frame_ratio": float(active.mean()),
        "spectral_centroid_hz": _stats(spec["centroid_hz"], active),
        "spectral_bandwidth_hz": _stats(spec["bandwidth_hz"], active),
        "spectral_rolloff_hz": _stats(spec["rolloff_hz"], active),
        "spectral_flatness": _stats(spec["flatness"], active),
        "spectral_flux": _stats(spec["flux"], active),
        "rms_envelope_dbfs": _stats(rms_env_db),
        "onset_count": int(onset_idx.size),
        "onset_density_per_s": float(onset_idx.size / duration),
        "onset_times_s": [float(t) for t in onset_times[:200]],
        "log_mel": {
            "n_mels": MEL_BANDS,
            "n_frames": int(log_mel.shape[1]),
            "fmin_hz": MEL_FMIN_HZ,
            "fmax_hz": sr / 2,
            "min_db": float(log_mel.min()),
            "max_db": float(log_mel.max()),
            "dominant_band_hz": float(
                mel_frequencies(MEL_BANDS, MEL_FMIN_HZ, sr / 2)[1:-1][
                    int(np.argmax(mel_power.mean(axis=1)))
                ]
            ),
        },
        "params": {
            "stft": {"n_fft": STFT_N_FFT, "hop": STFT_HOP, "window": "hann"},
            "mel": {
                "n_fft": MEL_N_FFT,
                "win_ms": MEL_WIN_MS,
                "hop_ms": MEL_HOP_MS,
                "n_mels": MEL_BANDS,
                "scale": "htk",
                "norm": "slaney-area",
            },
            "rolloff_fraction": ROLLOFF_FRACTION,
            "clip_peak": CLIP_PEAK,
            "active_frame_dbfs": ACTIVE_FRAME_DBFS,
            "onset": {
                "min_gap_s": ONSET_MIN_GAP_S,
                "peak_half_window_frames": ONSET_PEAK_HALF_WINDOW,
                "min_db": ONSET_MIN_DB,
                "local_median_s": ONSET_LOCAL_MEDIAN_S,
            },
            "waveform_buckets": WAVEFORM_BUCKETS,
            "stft_view_bins": STFT_VIEW_BINS,
        },
    }

    arrays: dict[str, NDArray[Any]] = {
        "times_s": times,
        "rms_envelope_db": rms_env_db,
        "centroid_hz": spec["centroid_hz"],
        "bandwidth_hz": spec["bandwidth_hz"],
        "rolloff_hz": spec["rolloff_hz"],
        "flatness": spec["flatness"],
        "flux": spec["flux"],
        "stft_view_db": stft_view_db.astype(np.float32),
        "stft_view_freqs_hz": np.linspace(0, sr / 2, STFT_VIEW_BINS + 1)[:-1],
        "mel_times_s": mel_times,
        "mel_freqs_hz": mel_frequencies(MEL_BANDS, MEL_FMIN_HZ, sr / 2)[1:-1],
        "log_mel_db": log_mel.astype(np.float32),
        "onset_strength": strength,
        "onset_times_s": onset_times,
        **wave,
    }
    return FeatureResult(version=DSP_VERSION, sample_rate=sr, summary=summary, arrays=arrays)
