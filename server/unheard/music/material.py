"""Musical material: ranked, traceable fragments cut from a recording (M4.6).

``source recording → material → motif → phrase → section → composition``. This is the first
stage. A fragment is an exact window of the canonical audio plus measured properties; nothing
here changes audio. Fragments are ranked by *quality for their role*, never by loudness:

* attack   — onset slice. Score = attack clarity (peak of the first 15 ms over the 60 ms of
             background before it) + sharpness (share of slice energy in its first 20 ms) +
             cleanliness (isolated: the next onset is not inside the slice). Loudness is not an input.
* tonal    — YIN voiced run. Usable only if confidence ≥ TONAL_MIN_CONFIDENCE, duration ≥ 80 ms and
             wobble < 1 semitone. Score = confidence + steadiness + duration.
* gesture  — the attack whose spectral centroid is the most unusual among the source's good
             attacks (a distinctive sound, e.g. the one metallic strike among footsteps).
* texture  — the steadiest 1.5–2 s window (short bed material).
* bed      — the sustained window chosen by the analysis (long atmosphere).
* cycle    — one period of a periodic source (engine, clock).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
from numpy.typing import NDArray

from unheard.music.analysis import SourceAnalysis

TONAL_MIN_CONFIDENCE = 0.80
TONAL_MIN_DURATION_S = 0.08
TONAL_MAX_WOBBLE_ST = 1.0
MAX_ATTACKS = 10
MAX_TONAL = 6


@dataclass
class Fragment:
    id: str
    kind: str  # attack | tonal | gesture | texture | bed | cycle
    start_s: float
    end_s: float
    score: float  # 0…1 quality for its kind
    props: dict[str, float] = field(default_factory=dict)

    @property
    def dur_s(self) -> float:
        return self.end_s - self.start_s

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "start_s": round(self.start_s, 4),
            "end_s": round(self.end_s, 4),
            "score": round(self.score, 4),
            **{k: round(v, 4) for k, v in self.props.items()},
        }


@dataclass
class Material:
    key: str
    attacks: list[Fragment]  # best first
    tonal: list[Fragment]  # usable runs only, best first
    gesture: Fragment | None
    texture: Fragment | None
    bed: Fragment | None
    cycle: Fragment | None
    tonal_center_midi: float | None  # confidence-weighted median of usable runs
    tonal_reliable: bool  # at least 2 usable runs → a melody may be built

    def to_json(self) -> dict[str, Any]:
        return {
            "attacks": [f.to_json() for f in self.attacks],
            "tonal": [f.to_json() for f in self.tonal],
            "gesture": self.gesture.to_json() if self.gesture else None,
            "texture": self.texture.to_json() if self.texture else None,
            "bed": self.bed.to_json() if self.bed else None,
            "cycle": self.cycle.to_json() if self.cycle else None,
            "tonal_center_midi": None
            if self.tonal_center_midi is None
            else round(self.tonal_center_midi, 2),
            "tonal_reliable": self.tonal_reliable,
        }


def _rms(x: NDArray[np.float64]) -> float:
    return float(np.sqrt(np.mean(x * x))) if x.size else 0.0


def _centroid(x: NDArray[np.float64], sr: int) -> float:
    if x.size < 64:
        return 0.0
    mag = np.abs(np.fft.rfft(x * np.hanning(x.size)))
    f = np.fft.rfftfreq(x.size, 1.0 / sr)
    return float((f * mag).sum() / max(mag.sum(), 1e-12))


def _attack_fragments(a: SourceAnalysis, x: NDArray[np.float64], sr: int) -> list[Fragment]:
    out: list[Fragment] = []
    for i, seg in enumerate(a.transients):
        on = int(seg.meta["onset_s"] * sr)
        s0, s1 = int(seg.start_s * sr), int(seg.end_s * sr)
        body = x[s0:s1]
        if body.size < int(0.02 * sr):
            continue
        pre = x[max(0, on - int(0.06 * sr)) : max(0, on - int(0.004 * sr))]
        head = x[on : on + int(0.015 * sr)]
        peak_head = max(float(np.max(np.abs(head))) if head.size else 0.0, 1e-6)
        clarity_db = 20 * np.log10(peak_head / (_rms(pre) + 1e-5))
        first20 = float(np.sum(x[on : on + int(0.02 * sr)] ** 2))
        sharp = first20 / max(float(np.sum(body**2)), 1e-12)
        # isolated = no other onset inside this slice (slices already end at the next onset: use IOI)
        ts = sorted(t.meta["onset_s"] for t in a.transients)
        k = ts.index(seg.meta["onset_s"])
        nxt = ts[k + 1] - ts[k] if k + 1 < len(ts) else 1.0
        clean = float(np.clip((nxt - 0.08) / 0.25, 0.0, 1.0))
        score = (
            0.4 * float(np.clip(clarity_db / 30.0, 0, 1))
            + 0.3 * float(np.clip(sharp * 1.5, 0, 1))
            + 0.3 * clean
        )
        out.append(
            Fragment(
                f"{a.key[:8]}:attack:{i}",
                "attack",
                seg.start_s,
                seg.end_s,
                score,
                {
                    "onset_s": seg.meta["onset_s"],
                    "clarity_db": float(clarity_db),
                    "sharpness": sharp,
                    "clean": clean,
                    "centroid_hz": _centroid(body, sr),
                    "strength": seg.score,
                },
            )
        )
    out.sort(key=lambda f: (-f.score, f.start_s))
    # keep a spread: skip attacks closer than 120 ms to a better one
    kept: list[Fragment] = []
    for f in out:
        if all(abs(f.props["onset_s"] - g.props["onset_s"]) > 0.12 for g in kept):
            kept.append(f)
        if len(kept) >= MAX_ATTACKS:
            break
    return kept


def _tonal_fragments(a: SourceAnalysis) -> list[Fragment]:
    out: list[Fragment] = []
    for i, r in enumerate(a.voiced_runs):
        conf = float(r.meta.get("confidence", 0.0))
        wob = float(r.meta["stability_st"])
        dur = r.end_s - r.start_s
        if conf < TONAL_MIN_CONFIDENCE or dur < TONAL_MIN_DURATION_S or wob > TONAL_MAX_WOBBLE_ST:
            continue
        score = (
            0.5 * conf
            + 0.3 * float(np.clip(1.0 - wob / TONAL_MAX_WOBBLE_ST, 0, 1))
            + 0.2 * float(np.clip(dur / 0.5, 0, 1))
        )
        out.append(
            Fragment(
                f"{a.key[:8]}:tonal:{i}",
                "tonal",
                r.start_s,
                r.end_s,
                score,
                {"midi": float(r.meta["midi"]), "confidence": conf, "wobble_st": wob},
            )
        )
    out.sort(key=lambda f: (-f.score, f.start_s))
    return out[:MAX_TONAL]


def extract_material(a: SourceAnalysis, x: NDArray[np.float64], sr: int) -> Material:
    attacks = _attack_fragments(a, x, sr)
    tonal = _tonal_fragments(a)

    gesture: Fragment | None = None
    good = [f for f in attacks if f.score >= 0.45]
    if len(good) >= 3:
        cs = np.log2(np.array([max(f.props["centroid_hz"], 50.0) for f in good]))
        z = np.abs(cs - np.median(cs))
        k = int(np.argmax(z))
        if z[k] > 0.4:  # at least ~⅖ octave away from the typical attack
            g = good[k]
            gesture = Fragment(
                g.id.replace("attack", "gesture"),
                "gesture",
                g.start_s,
                g.end_s,
                g.score,
                {**g.props, "distinctness_oct": float(z[k])},
            )

    bed: Fragment | None = None
    texture: Fragment | None = None
    if a.sustained is not None:
        s = a.sustained
        bed = Fragment(
            f"{a.key[:8]}:bed:0", "bed", s.start_s, s.end_s, float(np.clip(a.stability, 0, 1))
        )
        # steadiest ~1.8 s sub-window of the sustained window
        win = min(1.8, s.end_s - s.start_s)
        best, best_cv = s.start_s, 9.9
        for st in np.arange(s.start_s, s.end_s - win + 1e-9, 0.2):
            seg = x[int(st * sr) : int((st + win) * sr)]
            env = np.array([_rms(c) for c in np.array_split(seg, 18)])
            cv = float(np.std(env) / max(np.mean(env), 1e-9))
            if cv < best_cv:
                best, best_cv = float(st), cv
        texture = Fragment(
            f"{a.key[:8]}:texture:0", "texture", best, best + win, float(np.clip(1 - best_cv, 0, 1))
        )

    cycle: Fragment | None = None
    if a.period_s is not None and a.sustained is not None:
        st = a.sustained.start_s
        cycle = Fragment(
            f"{a.key[:8]}:cycle:0",
            "cycle",
            st,
            st + min(a.period_s, a.sustained.end_s - st),
            float(a.periodicity),
            {"period_s": float(a.period_s)},
        )

    center: float | None = None
    if tonal:
        w = np.array([f.props["confidence"] for f in tonal])
        m = np.array([f.props["midi"] for f in tonal])
        order = np.argsort(m)
        cw = np.cumsum(w[order])
        center = float(m[order][int(np.searchsorted(cw, cw[-1] / 2))])
    return Material(a.key, attacks, tonal, gesture, texture, bed, cycle, center, len(tonal) >= 2)
