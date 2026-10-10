"""Musical analysis of one canonical recording (ANALYSIS_VERSION 1).

Inputs are the canonical mono signal plus the M1 feature arrays (onsets, flatness, centroid,
flux, RMS). Everything is deterministic float64 NumPy. Pitch is only reported where the
signal is genuinely periodic (YIN threshold + voiced-run length); noise-like input yields
``voiced_ratio ≈ 0`` and no pitch segments, so no key is ever invented from broadband noise.

Measurements
* onset_times / strengths / density  — from M1 (peak-picked log-mel flux)
* periodicity   — strongest autocorrelation peak of the onset-strength curve in 0.25…2 s
                  (period_s, strength = r[lag]/r[0] in 0…1)
* stability     — 1 − CV of the linear RMS envelope over active frames (1 = steady texture)
* pitch (YIN)   — frame 2048 / hop 1024, cumulative-mean-normalised difference, threshold 0.15
* segments      — transient slices, one sustained window, voiced runs; each with exact source
                  start/end seconds so every musical event can be traced back
Harmonic/percussive separation (HPSS) is deliberately not implemented: onset strength +
flatness + voiced runs give the same routing decisions for this MVP at a fraction of the cost.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
from numpy.typing import NDArray

YIN_FRAME = 2048
YIN_HOP = 1024
YIN_THRESHOLD = 0.15
F0_MIN, F0_MAX = 80.0, 4000.0
MIN_RUN_S = 0.06
MAX_RUNS = 12
SLICE_PRE_S = 0.008
SLICE_MAX_S = 0.45
SUSTAIN_MIN_S = 1.0
SUSTAIN_MAX_S = 4.0
ACTIVE_DB = -60.0


@dataclass
class Segment:
    start_s: float
    end_s: float
    score: float
    meta: dict[str, float] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {
            "start_s": round(self.start_s, 4),
            "end_s": round(self.end_s, 4),
            "score": round(self.score, 4),
            **{k: round(v, 4) for k, v in self.meta.items()},
        }


@dataclass
class SourceAnalysis:
    key: str  # content hash (stable ordering key)
    duration_s: float
    rms_dbfs: float
    onset_times: list[float]
    onset_strengths: list[float]
    onset_density: float
    flatness_median: float
    centroid_median_hz: float
    flux_norm: float
    stability: float
    period_s: float | None
    periodicity: float
    voiced_ratio: float
    f0_median_hz: float | None
    pitch_stability_st: float | None
    transients: list[Segment]
    sustained: Segment | None
    voiced_runs: list[Segment]

    def to_json(self) -> dict[str, Any]:
        return {
            "version": 1,
            "duration_s": round(self.duration_s, 4),
            "rms_dbfs": round(self.rms_dbfs, 2),
            "onset_density": round(self.onset_density, 4),
            "n_onsets": len(self.onset_times),
            "flatness_median": round(self.flatness_median, 4),
            "centroid_median_hz": round(self.centroid_median_hz, 1),
            "flux_norm": round(self.flux_norm, 4),
            "stability": round(self.stability, 4),
            "period_s": None if self.period_s is None else round(self.period_s, 4),
            "periodicity": round(self.periodicity, 4),
            "voiced_ratio": round(self.voiced_ratio, 4),
            "f0_median_hz": None if self.f0_median_hz is None else round(self.f0_median_hz, 2),
            "pitch_stability_st": None
            if self.pitch_stability_st is None
            else round(self.pitch_stability_st, 3),
            "sustained": None if self.sustained is None else self.sustained.to_json(),
            "n_transients": len(self.transients),
            "n_voiced_runs": len(self.voiced_runs),
        }


def hz_to_midi(f: float) -> float:
    return float(69.0 + 12.0 * np.log2(f / 440.0))


def midi_to_hz(m: float) -> float:
    return float(440.0 * 2.0 ** ((m - 69.0) / 12.0))


def yin_pitch(
    x: NDArray[np.float64], sr: int
) -> tuple[NDArray[np.float64], NDArray[np.float64], NDArray[np.float64]]:
    """Frame-wise YIN. Returns (times_s, f0_hz (0 where unvoiced), cmnd_min)."""
    n = x.size
    n_frames = 1 + max(0, (n - YIN_FRAME) // YIN_HOP)
    tau_min = max(2, int(sr / F0_MAX))
    tau_max = min(YIN_FRAME // 2 - 1, int(sr / F0_MIN))
    half = YIN_FRAME // 2
    f0 = np.zeros(n_frames)
    cm = np.ones(n_frames)
    times = (np.arange(n_frames) * YIN_HOP + YIN_FRAME / 2) / sr
    nfft = 1 << (2 * half - 1).bit_length()
    for i in range(n_frames):
        fr = x[i * YIN_HOP : i * YIN_HOP + YIN_FRAME]
        if fr.size < YIN_FRAME or float(np.sqrt(np.mean(fr * fr))) < 10 ** (-50 / 20):
            continue
        a = fr[:half]
        spec = np.fft.rfft(fr, nfft)
        acf = np.fft.irfft(spec * np.conj(np.fft.rfft(a, nfft)), nfft)[: tau_max + 1]
        cs = np.concatenate([[0.0], np.cumsum(fr * fr)])
        # d(tau) = sum_j (x_j - x_{j+tau})^2 over j<half
        e0 = cs[half]
        e_tau = cs[half + np.arange(tau_max + 1)] - cs[np.arange(tau_max + 1)]
        d = e0 + e_tau - 2.0 * acf
        d[0] = 0.0
        run = np.cumsum(d[1:])
        cmnd = np.ones(tau_max + 1)
        cmnd[1:] = d[1:] * np.arange(1, tau_max + 1) / np.maximum(run, 1e-12)
        seg = cmnd[tau_min : tau_max + 1]
        below = np.where(seg < YIN_THRESHOLD)[0]
        if below.size:
            j = int(below[0])
            while j + 1 < seg.size and seg[j + 1] < seg[j]:
                j += 1
        else:
            j = int(np.argmin(seg))
        tau = tau_min + j
        cm[i] = float(cmnd[tau])
        if cm[i] >= 0.2 or tau <= 1 or tau >= tau_max:
            continue
        y0, y1, y2 = cmnd[tau - 1], cmnd[tau], cmnd[tau + 1]
        denom = y0 - 2 * y1 + y2
        shift = 0.5 * (y0 - y2) / denom if abs(denom) > 1e-12 else 0.0
        f0[i] = sr / (tau + float(np.clip(shift, -1, 1)))
    return times, f0, cm


def _voiced_runs(
    times: NDArray[np.float64],
    f0: NDArray[np.float64],
    dur: float,
    cmnd: NDArray[np.float64] | None = None,
) -> list[Segment]:
    runs: list[Segment] = []
    voiced = f0 > 0
    i, n = 0, f0.size
    step = float(times[1] - times[0]) if n > 1 else 0.02
    while i < n:
        if not voiced[i]:
            i += 1
            continue
        j = i
        while j + 1 < n and voiced[j + 1]:
            midi_a = hz_to_midi(f0[j])
            midi_b = hz_to_midi(f0[j + 1])
            if abs(midi_b - midi_a) > 2.5:  # note change: split
                break
            j += 1
        start = max(0.0, float(times[i]) - step / 2)
        end = min(dur, float(times[j]) + step / 2)
        if end - start >= MIN_RUN_S:
            midis = np.array([hz_to_midi(v) for v in f0[i : j + 1]])
            stab = float(np.std(midis))
            runs.append(
                Segment(
                    start,
                    end,
                    score=(end - start) / (1.0 + stab),
                    meta={
                        "midi": float(np.median(midis)),
                        "stability_st": stab,
                        # YIN confidence: 1 − mean cumulative-mean-normalised difference (1 = clean tone)
                        "confidence": 1.0
                        if cmnd is None
                        else float(np.clip(1.0 - np.mean(cmnd[i : j + 1]), 0.0, 1.0)),
                    },
                )
            )
        i = j + 1
    runs.sort(key=lambda s: (-s.score, s.start_s))
    return runs[:MAX_RUNS]


def _periodicity(strength: NDArray[np.float64], hop_s: float) -> tuple[float | None, float]:
    s = strength - strength.mean()
    if s.size < 8 or float(np.dot(s, s)) < 1e-9:
        return None, 0.0
    n = 1 << (2 * s.size - 1).bit_length()
    ac = np.fft.irfft(np.abs(np.fft.rfft(s, n)) ** 2, n)[: s.size]
    ac = ac / ac[0]
    lo = max(2, int(0.25 / hop_s))
    hi = min(s.size - 1, int(2.0 / hop_s))
    if hi <= lo:
        return None, 0.0
    lag = lo + int(np.argmax(ac[lo : hi + 1]))
    r = float(np.clip(ac[lag], 0.0, 1.0))
    return float(lag * hop_s), r


def analyze_source(
    key: str, samples: NDArray[np.float64], sr: int, arrays: dict[str, NDArray[np.float64]]
) -> SourceAnalysis:
    dur = samples.size / sr
    rms = float(np.sqrt(np.mean(samples * samples)))
    rms_db = float(20 * np.log10(max(rms, 1e-12)))
    env_db = np.asarray(arrays["rms_envelope_db"], dtype=np.float64)
    active = env_db > ACTIVE_DB
    # stability is judged over *all* frames (floored at −90 dBFS) so gaps between impulses count
    lin = 10 ** (np.maximum(env_db, -90.0) / 20) if env_db.size else np.array([rms])
    stability = float(np.clip(1.0 - np.std(lin) / max(np.mean(lin), 1e-9), 0.0, 1.0))
    flat = np.asarray(arrays["flatness"], dtype=np.float64)
    cent = np.asarray(arrays["centroid_hz"], dtype=np.float64)
    flux = np.asarray(arrays["flux"], dtype=np.float64)
    m = active if active.size == flat.size and active.any() else np.ones(flat.size, bool)
    flatness_med = float(np.median(flat[m]))
    centroid_med = float(np.median(cent[m]))
    flux_norm = float(np.mean(flux[m]) / max(np.mean(np.abs(samples)) * 50.0, 1e-9))
    flux_norm = float(np.clip(flux_norm, 0.0, 1.0))

    on_t = np.asarray(arrays["onset_times_s"], dtype=np.float64)
    strength = np.asarray(arrays["onset_strength"], dtype=np.float64)
    mel_t = np.asarray(arrays["mel_times_s"], dtype=np.float64)
    hop_s = float(mel_t[1] - mel_t[0]) if mel_t.size > 1 else 0.01
    on_str: list[float] = []
    for t in on_t:
        idx = int(np.clip(round((t - mel_t[0]) / hop_s), 0, strength.size - 1))
        on_str.append(float(strength[max(0, idx - 1) : idx + 2].max()))
    density = float(on_t.size / dur) if dur > 0 else 0.0
    period, per_strength = _periodicity(strength, hop_s)

    # transient slices, strongest first
    transients: list[Segment] = []
    for i, t in enumerate(on_t):
        nxt = on_t[i + 1] if i + 1 < on_t.size else dur
        end = float(min(dur, t + min(SLICE_MAX_S, max(0.06, nxt - t))))
        start = float(max(0.0, t - SLICE_PRE_S))
        transients.append(Segment(start, end, on_str[i], {"onset_s": float(t)}))
    transients.sort(key=lambda s: (-s.score, s.start_s))

    # sustained window: steadiest loud stretch
    sustained: Segment | None = None
    if dur >= SUSTAIN_MIN_S:
        win = min(SUSTAIN_MAX_S, dur)
        t_env = np.asarray(arrays["times_s"], dtype=np.float64)
        best = -1e9
        for st in np.arange(0.0, max(dur - win, 0.0) + 1e-9, 0.25):
            sel = (t_env >= st) & (t_env < st + win)
            if sel.sum() < 4:
                continue
            seg = 10 ** (env_db[sel] / 20)
            sc = float(np.mean(env_db[sel]) / 60.0 - np.std(seg) / max(np.mean(seg), 1e-9))
            if sc > best:
                best, sustained = sc, Segment(float(st), float(st + win), sc)

    t_p, f0, cm = yin_pitch(samples, sr)
    voiced_ratio = float(np.mean(f0 > 0)) if f0.size else 0.0
    runs = _voiced_runs(t_p, f0, dur, cm) if voiced_ratio > 0 else []
    f0_med: float | None = None
    pstab: float | None = None
    if runs:
        v = f0[f0 > 0]
        f0_med = float(np.median(v))
        pstab = float(np.median([r.meta["stability_st"] for r in runs]))  # within-note wobble

    return SourceAnalysis(
        key=key,
        duration_s=dur,
        rms_dbfs=rms_db,
        onset_times=[float(t) for t in on_t],
        onset_strengths=on_str,
        onset_density=density,
        flatness_median=flatness_med,
        centroid_median_hz=centroid_med,
        flux_norm=flux_norm,
        stability=stability,
        period_s=period if per_strength >= 0.15 else None,
        periodicity=per_strength,
        voiced_ratio=voiced_ratio,
        f0_median_hz=f0_med,
        pitch_stability_st=pstab,
        transients=transients,
        sustained=sustained,
        voiced_runs=runs,
    )
