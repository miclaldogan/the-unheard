"""M4.6 refinement: fragment diversification, organic dynamic arc, pitch reliability, legacy stability."""

from __future__ import annotations

from collections import Counter

import numpy as np

from tests.music_helpers import SR, make_source, steady_noise, three_sources
from unheard.music.analysis import analyze_source
from unheard.music.composer import register_octaves
from unheard.music.engine import analyse_and_plan, compose
from unheard.music.material import extract_material
from unheard.music.planner import canonical_plan_hash
from unheard.music.quality import evaluate


def footsteps(dur: float = 8.0, seed: int = 1) -> np.ndarray:
    """Irregular decaying noise bursts with a different timbre each step (distinct real-ish attacks)."""
    rng = np.random.default_rng(seed)
    n = int(dur * SR)
    x = np.zeros(n)
    t = 0.3
    while t < dur - 0.3:
        k = int(0.12 * SR)
        i = int(t * SR)
        burst = rng.standard_normal(k) * np.exp(-np.arange(k) / (0.025 * SR))
        a = rng.uniform(0.2, 0.95)
        y = np.zeros(k)
        acc = 0.0
        for j in range(k):
            acc = a * acc + (1 - a) * burst[j]
            y[j] = acc
        x[i : i + k] += 0.8 * y / np.max(np.abs(y))
        t += 0.32 + rng.uniform(-0.04, 0.04)
    return x


def bird(dur: float = 6.0) -> np.ndarray:
    """Three steady notes and three gliding chirps (glissandi) with silence between."""
    x = np.zeros(int(dur * SR))
    pos = 0.4
    for f0, f1, d in [
        (1800, 1800, 0.18),
        (2000, 2000, 0.18),
        (1500, 2100, 0.14),
        (2200, 1600, 0.14),
        (1700, 2300, 0.14),
        (1800, 1800, 0.18),
    ]:
        k = int(d * SR)
        i = int(pos * SR)
        ph = 2 * np.pi * np.cumsum(np.linspace(f0, f1, k)) / SR
        x[i : i + k] += 0.4 * np.sin(ph) * np.hanning(k)
        pos += d + 0.45
    return x


def two_tone_horn(dur: float = 6.0) -> np.ndarray:
    """400 + 500 Hz: heard near its partials, but a pitch tracker reports the common 100 Hz sub-harmonic."""
    t = np.arange(int(dur * SR)) / SR
    env = np.zeros(t.size)
    for s in (0.3, 2.2, 4.1):
        env[int(s * SR) : int(s * SR) + int(1.2 * SR)] = np.hanning(int(1.2 * SR))
    return 0.3 * (np.sin(2 * np.pi * 400 * t) + np.sin(2 * np.pi * 500 * t)) * env


def _rhythm_set():  # type: ignore[no-untyped-def]
    return [
        make_source(footsteps()),
        make_source(bird()),
        make_source(steady_noise()),
        make_source(steady_noise(6.0, 2)),
    ]


def _material(x):  # type: ignore[no-untyped-def]
    s = make_source(x)
    a = analyze_source(s.key, s.samples, SR, s.arrays)
    return a, extract_material(a, s.samples, SR)


# ------------------------------------------------------------------ A. fragment diversification
def test_fragment_reuse_is_capped_and_spread() -> None:
    plan = analyse_and_plan(_rhythm_set(), seed=7, duration_s=80, mode="composed")[0]
    bars = plan["duration_s"] / plan["bar_s"]
    cap = max(8, round(bars * 0.5))
    uses = Counter(e["fragment"] for e in plan["events"] if e["hierarchy"] == "foundation")
    assert len(uses) >= 4, "the groove should draw on several real attacks"
    assert max(uses.values()) <= cap + 3, (max(uses.values()), cap)
    assert len(plan["events"]) > 20  # still a composed piece, not an empty one


def test_worn_out_weak_positions_rest_instead_of_repeating() -> None:
    """Reuse is measured against the number of groove slots: heavy use of one fragment must not scale with length."""
    short = analyse_and_plan(_rhythm_set(), seed=7, duration_s=30, mode="composed")[0]
    long = analyse_and_plan(_rhythm_set(), seed=7, duration_s=90, mode="composed")[0]

    def worst(p):  # type: ignore[no-untyped-def]
        c = Counter(e["fragment"] for e in p["events"] if e["hierarchy"] == "foundation")
        return max(c.values()), sum(c.values())

    w_s, n_s = worst(short)
    w_l, n_l = worst(long)
    assert n_l > n_s  # more music…
    assert w_l / n_l < w_s / n_s + 0.05  # …without any single fragment dominating more


def test_diversification_stays_deterministic_and_source_traceable() -> None:
    p1 = analyse_and_plan(_rhythm_set(), seed=7, duration_s=40, mode="composed")[0]
    p2 = analyse_and_plan(list(reversed(_rhythm_set())), seed=7, duration_s=40, mode="composed")[0]
    assert canonical_plan_hash(p1) == canonical_plan_hash(p2)
    keys = set(p1["sources"])
    for e in p1["events"]:
        assert e["source"] in keys and e["source_end_s"] > e["source_start_s"] >= 0
        assert e["fragment"].startswith(
            e["source"][:8]
        )  # only fragments of the event's own recording


# ------------------------------------------------------------------ B. organic dynamic development
def test_organic_has_a_dynamic_arc_with_a_convergence_climax() -> None:
    res = compose(three_sources(), seed=5, duration_s=60, mode="organic")
    dyn = evaluate(res.plan, res.stems, res.master)["measured"]["dynamics"]
    assert 6.0 <= dyn["spread_db"] <= 15.0, dyn["spread_db"]
    assert dyn["climax_in_convergence"]
    assert min(dyn["convergence_over_ends_db"]) >= 3.0
    # an arc, not a louder piece: the master stays at the loudness target
    assert -21.0 < res.metrics["lufs_approx"] < -16.0


def test_organic_bed_recedes_when_the_foreground_enters() -> None:
    plan = analyse_and_plan(_rhythm_set(), seed=7, duration_s=60, mode="organic")[0]
    beds: dict[str, list[float]] = {}
    for e in plan["events"]:
        if e["hierarchy"] == "bed":
            beds.setdefault(e["section"], []).append(e["gain_db"])
    assert np.mean(beds["introduction"]) - np.mean(beds["convergence"]) >= 2.5
    firsts = sorted(e["t"] for e in plan["events"] if e["hierarchy"] == "lead")
    assert (
        firsts and firsts[0] >= plan["bar_s"] * 0.99
    )  # the bed is established for a bar before the lead enters


def test_crescendo_into_the_convergence_and_decrescendo_in_the_resolution() -> None:
    plan = analyse_and_plan(_rhythm_set(), seed=7, duration_s=90, mode="composed")[0]
    by_phrase: dict[str, list[float]] = {}
    for e in plan["events"]:
        if e["hierarchy"] in ("lead", "foundation") and e["phrase"] and not e.get("ghost"):
            by_phrase.setdefault(e["phrase"], []).append(e["velocity"])
    conv = [k for k in sorted(by_phrase) if k.startswith("con")]
    assert len(conv) >= 2, conv
    assert np.mean(by_phrase[conv[-1]]) >= np.mean(by_phrase[conv[0]]) - 1e-9
    res = [k for k in sorted(by_phrase) if k.startswith("res")]
    if len(res) >= 2:
        assert np.mean(by_phrase[res[-1]]) <= np.mean(by_phrase[res[0]]) + 1e-9


# ------------------------------------------------------------------ C. pitch reliability
def test_glissando_notes_join_a_source_that_already_has_reliable_notes() -> None:
    a, m = _material(bird())
    tiers = [int(f.props["tier"]) for f in m.tonal]
    assert m.tonal_reliable and tiers.count(1) >= 2 and tiers.count(2) >= 2
    assert len(m.tonal) >= 4  # the old gate left a 2-note bird motif
    centre = float(np.median([f.props["midi"] for f in m.tonal if f.props["tier"] == 1]))
    assert all(abs(f.props["midi"] - centre) <= 14.0 for f in m.tonal)
    assert any(
        f.props["wobble_st"] > 1.0 for f in m.tonal if f.props["tier"] == 2
    )  # genuine glides


def test_noise_and_clicks_never_get_tonal_material_even_with_the_looser_tier() -> None:
    for x in (steady_noise(6.0, 4), footsteps()):
        _a, m = _material(x)
        assert not m.tonal and not m.tonal_reliable and m.register_center_midi is None


def test_virtual_pitch_is_placed_by_its_audible_partials() -> None:
    a, m = _material(two_tone_horn())
    assert m.tonal_reliable
    assert all(f.props["virtual_pitch"] == 1.0 for f in m.tonal)
    assert (
        m.tonal_center_midi is not None and m.tonal_center_midi < 52
    )  # the tracker's ~100 Hz sub-harmonic
    assert (
        m.register_center_midi is not None and 64 <= m.register_center_midi <= 74
    )  # ≈ 400–500 Hz, where it is heard
    assert (
        register_octaves(m.tonal_center_midi) != 0
    )  # the old rule would have moved it up an octave
    assert register_octaves(m.register_center_midi) == 0


def test_a_clean_tone_is_not_called_virtual() -> None:
    from tests.music_helpers import tone_melody

    _a, m = _material(tone_melody())
    assert m.tonal_reliable and all(f.props["virtual_pitch"] == 0.0 for f in m.tonal)
    assert m.register_center_midi == m.tonal_center_midi


def test_horn_motif_keeps_its_audible_register_in_the_plan() -> None:
    srcs = [make_source(two_tone_horn()), make_source(footsteps()), make_source(steady_noise())]
    plan = analyse_and_plan(srcs, seed=3, duration_s=30, mode="composed")[0]
    notes = [e for e in plan["events"] if e["hierarchy"] == "lead" and "pitch_shift_st" in e]
    assert notes and all(
        abs(e["pitch_shift_st"]) < 6.0 for e in notes
    )  # no +12 st leap from a virtual pitch


# ------------------------------------------------------------------ legacy stays untouched
def test_legacy_plan_is_unchanged_by_the_refinement() -> None:
    plan = analyse_and_plan(three_sources(), seed=5, duration_s=30, mode="legacy")[0]
    assert (
        canonical_plan_hash(plan)[:16] == "c11a2c61c6976f1e"
    )  # recorded at f28831d, before M4.6 refinement
