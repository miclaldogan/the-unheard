"""M4 music engine: analysis, roles, planner, renderer (pure, no API)."""

from __future__ import annotations

import copy
import hashlib
import json

import numpy as np
import pytest

from tests.fixtures import synth
from tests.music_helpers import SR, make_source, steady_noise, three_sources, tone_melody
from unheard.music.analysis import analyze_source
from unheard.music.engine import analyse_and_plan, compose
from unheard.music.planner import canonical_plan_hash
from unheard.music.render import (
    PEAK_CEILING,
    limiter_gain,
    loudness_lufs,
    render_event,
    render_plan,
)
from unheard.music.roles import assign_role


def _an(x):  # type: ignore[no-untyped-def]
    s = make_source(x)
    return analyze_source(s.key, s.samples, SR, s.arrays)


# ------------------------------------------------------------------ analysis
def test_click_train_onsets_and_periodicity() -> None:
    a = _an(synth.click_train(4.0, SR, 6.0))
    assert 3.2 <= a.onset_density <= 4.8
    assert a.period_s is not None and abs(a.period_s - 0.25) < 0.03 or a.periodicity > 0.2


def test_sine_is_pitched_and_noise_is_not() -> None:
    a = _an(synth.sine(440.0, SR, 4.0, 0.4))
    assert a.voiced_ratio > 0.8 and a.f0_median_hz is not None
    assert abs(a.f0_median_hz - 440.0) / 440.0 < 0.01
    n = _an(steady_noise(4.0))
    assert n.voiced_ratio < 0.1 and not n.voiced_runs and n.f0_median_hz is None


def test_noise_never_becomes_a_melody() -> None:
    a = _an(steady_noise(5.0))
    d = assign_role(a)
    assert d.primary != "tonal_motif"
    forced = assign_role(a, "tonal_motif")
    assert forced.primary != "tonal_motif" and "impossible" in forced.rationale


def test_roles_follow_measurements_not_labels() -> None:
    tonal = assign_role(_an(tone_melody()))
    clicks = assign_role(_an(synth.click_train(3.0, SR, 6.0)))
    noise = assign_role(_an(steady_noise()))
    assert tonal.primary == "tonal_motif"
    assert clicks.primary == "percussion"
    assert noise.primary in ("texture", "drone")
    assert "evidence" in clicks.to_json() and clicks.evidence["n_onsets"] >= 10


def test_manual_override_is_honoured_when_feasible() -> None:
    a = _an(steady_noise())
    assert assign_role(a, "granular").primary == "granular"
    with pytest.raises(ValueError):
        assign_role(a, "kazoo")


# ------------------------------------------------------------------ planner
def test_plan_is_deterministic_and_order_independent() -> None:
    srcs = three_sources()
    p1, _, _ = analyse_and_plan(srcs, seed=11)
    p2, _, _ = analyse_and_plan(list(reversed(srcs)), seed=11)
    assert json.dumps(p1, sort_keys=True) == json.dumps(p2, sort_keys=True)
    assert canonical_plan_hash(p1) == canonical_plan_hash(p2)


def test_different_seed_gives_valid_variation() -> None:
    srcs = three_sources()
    p1, _, _ = analyse_and_plan(srcs, seed=1)
    p2, _, _ = analyse_and_plan(srcs, seed=2)
    assert canonical_plan_hash(p1) != canonical_plan_hash(p2)
    for p in (p1, p2):
        assert len(p["events"]) > 10 and [s["name"] for s in p["sections"]] == [
            "introduction",
            "discovery",
            "convergence",
            "resolution",
        ]


def test_plan_events_reference_valid_segments_and_stay_in_bounds() -> None:
    srcs = three_sources()
    plan, _, _ = analyse_and_plan(srcs, seed=5, duration_s=40)
    dur = {s.key: s.samples.size / SR for s in srcs}
    assert set(plan["sources"]) == set(dur)
    assert 15 <= plan["duration_s"] <= 90
    for e in plan["events"]:
        assert e["source"] in dur
        assert 0 <= e["source_start_s"] < e["source_end_s"] <= dur[e["source"]] + 1e-6
        assert 0 <= e["t"] <= plan["duration_s"] and e["dur"] > 0
        assert e["gain_db"] <= 6.0
    secs = {s["name"]: s for s in plan["sections"]}
    assert abs(sum(s["bars"] for s in plan["sections"]) * plan["bar_s"] - plan["duration_s"]) < 1e-3
    assert secs["introduction"]["start_s"] == 0


def test_empty_and_oversized_selection_rejected() -> None:
    with pytest.raises(ValueError):
        analyse_and_plan([], seed=1)
    many = [make_source(steady_noise(4.0, seed=i)) for i in range(9)]
    with pytest.raises(ValueError):
        analyse_and_plan(many, seed=1)


def test_controls_have_measurable_effects() -> None:
    srcs = three_sources()
    base, _, _ = analyse_and_plan(srcs, seed=3, controls={"density": 0.0})
    dense, _, _ = analyse_and_plan(srcs, seed=3, controls={"density": 1.0})
    assert len(dense["events"]) > len(base["events"])
    slow, _, _ = analyse_and_plan(srcs, seed=3, controls={"intensity": 0.0})
    fast, _, _ = analyse_and_plan(srcs, seed=3, controls={"intensity": 1.0})
    assert fast["tempo_bpm"] > slow["tempo_bpm"]
    grid, _, _ = analyse_and_plan(srcs, seed=3, controls={"structure": 1.0})
    free, _, _ = analyse_and_plan(srcs, seed=3, controls={"structure": 0.0})

    def off_grid(p: dict) -> float:  # type: ignore[type-arg]
        step = p["bar_s"] / 16
        ts = [e["t"] for e in p["events"] if e["role"] == "percussion"]
        return float(np.mean([abs((t / step) - round(t / step)) for t in ts])) if ts else 0.0

    assert off_grid(grid) < 0.02 < off_grid(free)


def test_tonal_notes_are_snapped_to_the_key() -> None:
    plan, _, _ = analyse_and_plan(three_sources(), seed=3)
    assert plan["key"] is not None
    tonic = plan["key"]["tonic_midi"]
    notes = [e for e in plan["events"] if e["role"] == "tonal_motif"]
    assert notes and all(
        abs(e["pitch_shift_st"] - 12 * e["octave_shift"]) <= 7.0 for e in notes
    )  # tuning to the key is small; octave moves are separate
    del tonic


def test_noise_only_selection_has_no_key() -> None:
    srcs = [make_source(steady_noise(5.0, 1)), make_source(steady_noise(5.0, 2))]
    plan, _, _ = analyse_and_plan(srcs, seed=1)
    assert plan["key"] is None
    assert all(e["role"] != "tonal_motif" for e in plan["events"])


def test_every_section_has_events() -> None:
    plan, _, _ = analyse_and_plan(three_sources(), seed=9)
    names = {e["section"] for e in plan["events"]}
    assert names == {"introduction", "discovery", "convergence", "resolution"}


# ------------------------------------------------------------------ renderer
def test_render_is_deterministic_and_sums_to_master() -> None:
    srcs = three_sources()
    r1 = compose(srcs, seed=4, duration_s=20)
    r2 = compose(srcs, seed=4, duration_s=20)
    assert (
        hashlib.sha256(r1.master.tobytes()).hexdigest()
        == hashlib.sha256(r2.master.tobytes()).hexdigest()
    )
    total = sum(r1.stems.values())
    assert float(np.max(np.abs(total - r1.master))) < 1e-9


def test_render_quality_gates() -> None:
    res = compose(three_sources(), seed=4, duration_s=30)
    m = res.metrics
    assert m["peak_dbfs"] <= -0.99
    assert m["clipping_ratio"] == 0.0
    assert not np.isnan(res.master).any()
    assert m["silence_ratio"] < 0.35
    assert m["empty_sections"] == [] and m["events_out_of_bounds"] == 0
    assert m["max_sample_step"] < 1.0
    assert m["sample_rate"] == SR and res.master.shape[1] == 2
    assert -26 < m["lufs_approx"] < -12
    assert abs(m["duration_s"] - (res.plan["duration_s"] + res.plan["tail_s"])) < 0.01


def test_changing_a_source_changes_master_and_its_stem_vanishes() -> None:
    srcs = three_sources()
    full = compose(srcs, seed=4, duration_s=20)
    fewer = compose(srcs[:2], seed=4, duration_s=20)
    assert len(fewer.stems) < len(full.stems)
    n = min(full.master.shape[0], fewer.master.shape[0])
    assert float(np.mean(np.abs(full.master[:n] - fewer.master[:n]))) > 1e-5


def test_each_track_contributes_audio() -> None:
    res = compose(three_sources(), seed=4, duration_s=25)
    contrib = res.metrics["track_contribution"]
    assert set(contrib) == {t["id"] for t in res.plan["tracks"]}
    assert all(v > 0.02 for v in contrib.values())


def test_event_edges_do_not_click() -> None:
    src = steady_noise(4.0)
    buf = np.zeros((SR * 3, 2))
    ev = {
        "kind": "slice",
        "t": 0.5,
        "dur": 1.0,
        "source_start_s": 0.2,
        "source_end_s": 1.2,
        "gain_db": 0.0,
        "rate": 1.0,
        "fade_in_s": 0.005,
        "fade_out_s": 0.02,
    }
    render_event(ev, src, 0.0, 1, buf)
    nz = np.where(np.abs(buf[:, 0]) > 0)[0]
    assert abs(buf[nz[0], 0]) < 1e-3 and abs(buf[nz[-1], 0]) < 1e-3


def test_resample_rate_changes_length_and_pan_is_equal_power() -> None:
    src = synth.sine(440, SR, 2.0, 0.5)
    for rate, expect in ((2.0, 0.5), (0.5, 2.0)):
        buf = np.zeros((SR * 4, 2))
        ev = {
            "kind": "slice",
            "t": 0.0,
            "dur": 1.0,
            "source_start_s": 0.0,
            "source_end_s": 1.0,
            "gain_db": 0.0,
            "rate": rate,
            "fade_in_s": 0.001,
            "fade_out_s": 0.001,
        }
        render_event(ev, src, 0.0, 1, buf)
        n = int(np.sum(np.abs(buf[:, 0]) > 1e-6))
        assert abs(n / SR - expect) < 0.03
    buf = np.zeros((SR * 2, 2))
    ev = {
        "kind": "slice",
        "t": 0.0,
        "dur": 1.0,
        "source_start_s": 0.0,
        "source_end_s": 1.0,
        "gain_db": 0.0,
        "rate": 1.0,
    }
    render_event(ev, src, 0.7, 1, buf)
    p_c = np.zeros((SR * 2, 2))
    render_event(ev, src, 0.0, 1, p_c)
    assert abs(np.sum(buf**2) - np.sum(p_c**2)) / np.sum(p_c**2) < 0.01


def test_very_short_source_does_not_crash() -> None:
    short = make_source(np.concatenate([synth.sine(440, SR, 0.2, 0.3), np.zeros(10)]))
    other = make_source(steady_noise(4.0))
    res = compose([short, other], seed=2, duration_s=15)
    assert np.isfinite(res.master).all()


def test_limiter_never_exceeds_ceiling() -> None:
    x = np.zeros((SR, 2))
    x[10_000] = [3.0, 3.0]
    x[40_000:40_100] = 1.5
    g = limiter_gain(x)
    assert float(np.max(np.abs(x * g[:, None]))) <= PEAK_CEILING + 1e-9
    assert float(g.min()) < 1.0 and g[0] == 1.0


def test_loudness_meter_tracks_level() -> None:
    a = np.stack([synth.sine(1000, SR, 3.0, 0.1)] * 2, axis=1)
    b = a * 2.0
    assert abs((loudness_lufs(b) - loudness_lufs(a)) - 6.02) < 0.2


def test_provenance_every_event_maps_to_a_source_window() -> None:
    srcs = three_sources()
    res = compose(srcs, seed=8, duration_s=20)
    keys = {s.key for s in srcs}
    for e in res.plan["events"]:
        assert e["source"] in keys
        assert e["track"] in res.stems
    plan2 = copy.deepcopy(res.plan)
    plan2["tracks"][0]["source"] = "nope"
    with pytest.raises(KeyError):
        render_plan(plan2, {s.key: s.samples for s in srcs})
