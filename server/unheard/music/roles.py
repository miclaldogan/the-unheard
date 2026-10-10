"""Source-role assignment from measured acoustics (no label → instrument table).

Each role has a score in 0…1 computed from the analysis; the primary role is the highest
score above ``MIN_ROLE_SCORE`` (otherwise the conservative default ``texture``). Every
decision returns its evidence so the UI can answer "why is this recording percussion?".
Semantic labels are never an input: two water recordings with different measurements can
receive different roles.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from unheard.music.analysis import SourceAnalysis

ROLES = (
    "texture",
    "drone",
    "rhythmic_texture",
    "percussion",
    "tonal_motif",
    "accent",
    "granular",
)
MIN_ROLE_SCORE = 0.30
SECONDARY_MIN = 0.50
SECONDARY_RATIO = 0.80


def _c(x: float) -> float:
    return max(0.0, min(1.0, x))


@dataclass
class RoleDecision:
    primary: str
    secondary: str | None
    scores: dict[str, float]
    evidence: dict[str, Any]
    rationale: str
    overridden: bool = False

    def to_json(self) -> dict[str, Any]:
        return {
            "primary": self.primary,
            "secondary": self.secondary,
            "scores": {k: round(v, 4) for k, v in self.scores.items()},
            "evidence": self.evidence,
            "rationale": self.rationale,
            "overridden": self.overridden,
        }


def role_scores(a: SourceAnalysis) -> dict[str, float]:
    """Scores in 0…1. Power-domain spectral flatness is tilt-dominated on real recordings
    (rain/wind/traffic all sit below 1e-3), so noisiness is judged by the *absence of pitch*
    plus steadiness rather than by thresholding flatness."""
    n_on = len(a.onset_times)
    mean_str = sum(a.onset_strengths) / n_on if n_on else 0.0
    unvoiced = _c(1.0 - 2.5 * a.voiced_ratio)
    low = _c(1.0 - a.centroid_median_hz / 3000.0)
    perc = 0.0
    if n_on >= 2:
        perc = _c(a.onset_density / 1.5) * 0.6 + _c(mean_str / 12.0) * 0.4
        perc *= 1.0 - 0.5 * a.stability  # steady sounds with ripples are not hits
    tonal_s = 0.0
    if a.voiced_ratio >= 0.08 and len(a.voiced_runs) >= 2:
        pst = a.pitch_stability_st if a.pitch_stability_st is not None else 3.0
        tonal_s = _c(a.voiced_ratio * 3.0) * (0.55 + 0.45 * _c(1.0 - pst / 3.0))
    drone = (
        a.stability * low * (0.5 + 0.5 * (1.0 - _c(a.onset_density / 1.0))) * (0.6 + 0.4 * unvoiced)
    )
    texture = a.stability * (0.45 + 0.55 * unvoiced) * (1.0 - 0.6 * perc)
    rhythmic = 0.0
    if a.period_s is not None:
        rhythmic = _c(a.periodicity * 1.3) * _c((a.stability - 0.2) / 0.5)
        rhythmic *= 1.0 - 0.6 * _c(a.voiced_ratio * 2.0)  # pitched material prefers melody
    accent = 0.0
    if 1 <= n_on <= 3:
        accent = _c(mean_str / 10.0) * 0.8 * (1.0 - 0.7 * a.stability)
    granular = 0.45 * unvoiced * (1.0 - a.stability) + 0.2 * _c(a.flux_norm * 3)
    return {
        "texture": _c(texture),
        "drone": _c(drone),
        "rhythmic_texture": _c(rhythmic),
        "percussion": _c(perc),
        "tonal_motif": _c(tonal_s),
        "accent": _c(accent),
        "granular": _c(granular),
    }


def assign_role(a: SourceAnalysis, override: str | None = None) -> RoleDecision:
    scores = role_scores(a)
    n_on = len(a.onset_times)
    evidence: dict[str, Any] = {
        "onset_density": round(a.onset_density, 3),
        "n_onsets": n_on,
        "flatness_median": round(a.flatness_median, 3),
        "centroid_median_hz": round(a.centroid_median_hz, 0),
        "stability": round(a.stability, 3),
        "periodicity": round(a.periodicity, 3),
        "period_s": None if a.period_s is None else round(a.period_s, 3),
        "voiced_ratio": round(a.voiced_ratio, 3),
        "f0_median_hz": None if a.f0_median_hz is None else round(a.f0_median_hz, 1),
    }
    feasible = dict(scores)
    # roles that need material the source does not have are never assignable
    if not a.voiced_runs:
        feasible["tonal_motif"] = 0.0
    if n_on < 1:
        feasible["percussion"] = 0.0
        feasible["accent"] = 0.0
    if a.sustained is None:
        for r in ("texture", "drone", "rhythmic_texture"):
            feasible[r] = 0.0
    if override:
        if override not in ROLES:
            raise ValueError(f"unknown role {override!r}")
        if feasible[override] > 0.0 or override == "granular":
            return RoleDecision(
                override, None, scores, evidence, f"manual override to {override}", True
            )
        note = f"override {override!r} impossible for this recording; used measured role"
    else:
        note = ""
    order = sorted(ROLES, key=lambda r: (-feasible[r], ROLES.index(r)))
    primary = order[0]
    if feasible[primary] < MIN_ROLE_SCORE:
        primary = "texture" if a.sustained is not None else "granular"
        why = f"no role scored ≥ {MIN_ROLE_SCORE}; conservative default {primary}"
    else:
        why = _why(primary, a, scores)
    second = order[1]
    secondary = (
        second
        if second != primary
        and feasible[second] >= SECONDARY_MIN
        and feasible[second] >= SECONDARY_RATIO * feasible[primary]
        else None
    )
    return RoleDecision(primary, secondary, scores, evidence, (note + " " + why).strip())


def _why(role: str, a: SourceAnalysis, s: dict[str, float]) -> str:
    n = len(a.onset_times)
    if role == "percussion":
        return f"{n} clear onsets ({a.onset_density:.2f}/s) → rhythmic hits"
    if role == "tonal_motif":
        return f"pitched {a.voiced_ratio:.0%} of the time near {a.f0_median_hz:.0f} Hz → melody"
    if role == "drone":
        return f"steady (stability {a.stability:.2f}) and dark (centroid {a.centroid_median_hz:.0f} Hz) → drone"
    if role == "rhythmic_texture":
        return f"periodic modulation every {a.period_s:.2f} s (strength {a.periodicity:.2f}) → locked to the grid"
    if role == "accent":
        return f"{n} strong isolated onset(s) → transition accents"
    if role == "granular":
        return "noisy and unsteady → granular cloud"
    return f"sustained broadband material (flatness {a.flatness_median:.2f}, stability {a.stability:.2f}) → atmosphere"
