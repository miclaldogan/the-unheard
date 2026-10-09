"""M4.6 motif/phrase composer: material, motifs, variation, phrases, conversation, groove, silence,
foreground limits, tonal reliability, determinism and renderer compatibility (synthetic sources)."""

from __future__ import annotations

import copy
import hashlib

import numpy as np
import pytest

from tests.fixtures import synth
from tests.music_helpers import SR, make_source, steady_noise, three_sources, tone_melody
from unheard.music.analysis import analyze_source, yin_pitch
from unheard.music.composer import (
    FOREGROUND_LIMIT,
    REGISTER_HIGH,
    REGISTER_LOW,
    SPECS,
    Motif,
    Note,
    build_tonal_motif,
    enforce_foreground,
    register_octaves,
    v_answer,
    v_density,
    v_fragment,
    v_register,
    v_retrograde,
    v_shift,
)
from unheard.music.engine import analyse_and_plan, compose
from unheard.music.material import Fragment, Material, extract_material
from unheard.music.planner import canonical_plan_hash, rng_for
from unheard.music.quality import evaluate
from unheard.music.render import render_event, sola_stretch


def _material(x):  # type: ignore[no-untyped-def]
    s = make_source(x)
    a = analyze_source(s.key, s.samples, SR, s.arrays)
    return s, a, extract_material(a, s.samples, SR)


def _plan(mode: str, seed: int = 5, dur: float = 30, **kw):  # type: ignore[no-untyped-def]
    return analyse_and_plan(three_sources(), seed=seed, duration_s=dur, mode=mode, **kw)[0]


# ------------------------------------------------------------------ material
def test_material_extraction_is_deterministic() -> None:
    x = synth.click_train(3.0, SR, 6.0)
    m1 = _material(x)[2]
    m2 = _material(x)[2]
    assert [f.to_json() for f in m1.attacks] == [f.to_json() for f in m2.attacks]
    assert m1.bed and m1.texture and m1.cycle


def test_fragment_ranking_does_not_reward_loudness() -> None:
    x = synth.click_train(3.0, SR, 6.0, amp=0.9)
    loud = _material(x)[2]
    quiet = _material(0.3 * x)[2]
    assert [round(f.score, 2) for f in loud.attacks] == pytest.approx(
        [round(f.score, 2) for f in quiet.attacks], abs=0.06
    )
    assert [f.start_s for f in loud.attacks] == [f.start_s for f in quiet.attacks]


def test_noise_has_no_tonal_material() -> None:
    m = _material(steady_noise(5.0))[2]
    assert not m.tonal and not m.tonal_reliable and m.tonal_center_midi is None


def test_low_confidence_pitch_is_gated_out() -> None:
    rng = np.random.default_rng(1)
    tone = synth.sine(330.0, SR, 5.0, 0.15) + 0.4 * rng.standard_normal(
        5 * SR
    )  # tone buried in noise
    m = _material(np.clip(tone, -1, 1))[2]
    assert not m.tonal_reliable


def test_clean_melody_is_reliable() -> None:
    m = _material(tone_melody())[2]
    assert (
        m.tonal_reliable
        and m.tonal_center_midi is not None
        and all(f.props["confidence"] >= 0.8 for f in m.tonal)
    )


# ------------------------------------------------------------------ tonal motif construction
def _fake_material(midis: list[float], conf: list[float]) -> Material:
    frags = [
        Fragment(
            f"fake:tonal:{i}",
            "tonal",
            i * 0.6,
            i * 0.6 + 0.4,
            0.9,
            {"midi": m, "confidence": c, "wobble_st": 0.2},
        )
        for i, (m, c) in enumerate(zip(midis, conf, strict=True))
    ]
    center = float(np.median(midis))
    return Material("fake", [], frags, None, None, None, None, center, True)


def test_register_is_moved_by_whole_octaves_only() -> None:
    assert (
        register_octaves(97.0) == -1 and register_octaves(43.0) == 1 and register_octaves(70.0) == 0
    )
    assert REGISTER_LOW <= 97 + 12 * register_octaves(97.0) <= REGISTER_HIGH
    m = build_tonal_motif(
        "A",
        "fake",
        _fake_material([97.0, 99.0, 97.0], [0.95] * 3),
        0.1,
        rng_for(1, "t"),
        SPECS["composed"],
    )
    assert m is not None
    assert all(
        abs(abs(n.shift_st) - 12) < 1.0 for n in m.notes
    )  # an octave (+ tiny tuning), not a pentatonic remap


def test_suspected_octave_error_is_folded_into_the_tonal_centre() -> None:
    mat = _fake_material([60.0, 60.0, 72.0, 60.0], [0.95, 0.95, 0.82, 0.95])
    m = build_tonal_motif("A", "fake", mat, 0.1, rng_for(1, "t"), SPECS["composed"])
    assert m is not None
    folded = [n for n in m.notes if "octave_folded" in n.flags]
    assert len(folded) == 1 and folded[0].midi_src == 72.0
    assert abs(folded[0].midi_src + folded[0].shift_st - 60.0) < 0.5  # lands at the centre's octave


def test_unreliable_source_yields_no_melody() -> None:
    mat = _fake_material([60.0], [0.95])
    mat.tonal_reliable = False
    assert build_tonal_motif("A", "fake", mat, 0.1, rng_for(1, "t"), SPECS["composed"]) is None


def test_pentatonic_strategy_snaps_and_contour_does_not() -> None:
    mat = _fake_material([60.0, 61.4, 65.3], [0.95] * 3)
    c = build_tonal_motif("A", "fake", mat, 0.1, rng_for(1, "t"), SPECS["composed"], "contour")
    p = build_tonal_motif("A", "fake", mat, 0.1, rng_for(1, "t"), SPECS["composed"], "pentatonic")
    assert c and p
    tgt_c = [n.midi_src + n.shift_st for n in c.notes]
    tgt_p = [n.midi_src + n.shift_st for n in p.notes]
    assert tgt_c != tgt_p and all(
        abs(t - round(t)) < 1e-6 or abs(t - round(t)) > 0.3 for t in tgt_c
    )
    centre = mat.tonal_center_midi or 0.0
    assert all(round(t - centre) % 12 in (0, 3, 5, 7, 10) for t in tgt_p)


# ------------------------------------------------------------------ motif variation relations
def _rhythm_motif() -> Motif:
    frags = [
        Fragment(
            f"s:attack:{i}",
            "attack",
            i,
            i + 0.2,
            0.5 + 0.05 * i,
            {"onset_s": float(i), "centroid_hz": 2000.0},
        )
        for i in range(5)
    ]
    notes = [Note(float(s), frags[i], 0.5 + 0.1 * i) for i, s in enumerate((0, 3, 6, 8, 12))]
    return Motif("s:A", "A", "rhythm", "s", 16, notes)


def test_variations_keep_a_documented_relation_to_the_parent() -> None:
    a = _rhythm_motif()
    sh = v_shift(a, "A'", 2.0)
    assert sh.relation == {"parent": a.id, "operator": "shift", "steps": 2.0}
    assert sorted(n.frag.id for n in sh.notes) == sorted(n.frag.id for n in a.notes)
    assert {int(n.step) for n in sh.notes} == {(int(n.step) + 2) % 16 for n in a.notes}

    dn = v_density(a, "A'''", 0.6)
    assert 1 <= len(dn.notes) < len(a.notes) and {n.frag.id for n in dn.notes} <= {
        n.frag.id for n in a.notes
    }
    ghosts = [Fragment("s:attack:9", "attack", 9, 9.2, 0.4, {})]
    gd = v_density(a, "B", 1.0, ghosts)
    assert len(gd.notes) > len(a.notes) and any(n.ghost for n in gd.notes)

    alts = [Fragment(f"s:attack:{i}", "attack", 20 + i, 20.2 + i, 0.4, {}) for i in range(2)]
    fr = v_fragment(a, "A''", alts)
    assert [round(n.step, 3) for n in fr.notes] == [round(n.step, 3) for n in a.notes]
    assert any(x.frag.id != y.frag.id for x, y in zip(fr.notes, a.notes, strict=True))

    t = build_tonal_motif(
        "T",
        "fake",
        _fake_material([60, 62, 65, 69], [0.95] * 4),
        0.1,
        rng_for(2, "t"),
        SPECS["composed"],
    )
    assert t is not None
    rg = v_register(t, "B", 1)
    base_iv = np.diff([n.midi_src + n.shift_st for n in t.notes])
    new_iv = np.diff([n.midi_src + n.shift_st for n in rg.notes])
    assert np.allclose(base_iv, new_iv) and rg.relation and rg.relation["octaves"] == 1
    rt = v_retrograde(t, "A''")
    assert [n.midi_src for n in rt.notes] == [n.midi_src for n in t.notes][::-1]
    assert [n.step for n in rt.notes] == [n.step for n in t.notes]
    an = v_answer(t, "A'")
    assert len(an.notes) == 2 and an.relation and an.relation["parent"] == t.id


# ------------------------------------------------------------------ phrases, form, provenance
def test_composed_plan_has_phrases_form_and_variation() -> None:
    p = _plan("composed")
    assert p["mode"] == "composed" and p["motifs"] and p["phrases"]
    assert [s["name"] for s in p["sections"]] == [
        "introduction",
        "discovery",
        "convergence",
        "resolution",
    ]
    assert all(
        2 <= ph["bars"] <= 5 for ph in p["phrases"]
    )  # 4-bar phrases; a remainder is merged, never a 1-bar orphan
    assert any(ph["bars"] == 4 for ph in p["phrases"])
    assert set(p["form"]) == {"introduction", "discovery", "convergence", "resolution"}
    ops = {m["relation"]["operator"] for m in p["motifs"] if m["relation"]}
    assert len(ops) >= 2  # real variation, not only repetition
    variants = [
        e
        for e in p["events"]
        if e.get("variation") in {"A'", "A''", "A'''", "B", "F'", "Fa", "F''"}
    ]
    assert variants and all(e["motif"] for e in variants)
    # every variant motif names a registered parent
    ids = {m["id"] for m in p["motifs"]}
    assert all(m["relation"]["parent"] in ids for m in p["motifs"] if m["relation"])


def test_every_event_traces_to_a_real_source_window() -> None:
    srcs = three_sources()
    for mode in ("organic", "composed"):
        p = analyse_and_plan(srcs, seed=3, duration_s=30, mode=mode)[0]
        dur = {s.key: s.samples.size / SR for s in srcs}
        for e in p["events"]:
            assert e["source"] in dur and e["fragment"] and e["track"]
            assert 0 <= e["source_start_s"] < e["source_end_s"] <= dur[e["source"]] + 1e-6
            assert -1e-6 <= e["t"] <= p["duration_s"] + 1e-6 and e["dur"] > 0
        assert {t["source"] for t in p["tracks"]} <= set(dur)


def test_regeneration_is_stable_and_order_independent() -> None:
    srcs = three_sources()
    a = analyse_and_plan(srcs, seed=9, duration_s=30, mode="composed")[0]
    b = analyse_and_plan(list(reversed(srcs)), seed=9, duration_s=30, mode="composed")[0]
    c = analyse_and_plan(srcs, seed=10, duration_s=30, mode="composed")[0]
    assert canonical_plan_hash(a) == canonical_plan_hash(b) != canonical_plan_hash(c)
    r1 = compose(srcs, seed=9, duration_s=20, mode="composed")
    r2 = compose(srcs, seed=9, duration_s=20, mode="composed")
    assert (
        hashlib.sha256(r1.master.tobytes()).hexdigest()
        == hashlib.sha256(r2.master.tobytes()).hexdigest()
    )


# ------------------------------------------------------------------ conversation, silence, foreground
def test_call_and_response_is_scheduled_in_the_rests() -> None:
    p = _plan("composed")
    assert p["conversation"] and p["conversation"][0]["evidence"]["score"] >= 0.45
    ev = p["events"]
    resp = [e for e in ev if e.get("variation") == "response"]
    assert resp
    for phrase in {e["phrase"] for e in resp}:
        lead = [e for e in ev if e["phrase"] == phrase and e["hierarchy"] == "lead"]
        mine = [e for e in resp if e["phrase"] == phrase]
        assert (
            lead and min(e["t"] for e in mine) >= max(e["t"] for e in lead) + 0.05
        )  # the answer waits for the call
        for r in mine:
            assert not any(
                le["t"] < r["t"] + 0.1 and r["t"] < le["t"] + min(le["dur"], le["fg_window_s"])
                for le in lead
            )
    assert all(e["response_to"] for e in resp)


def test_responder_compatibility_comes_from_evidence() -> None:
    ev = _plan("composed")["conversation"][0]["evidence"]
    assert {
        "temporal_fit",
        "spectral_contrast",
        "tonal_consonance",
        "pulse_relation",
        "score",
    } <= set(ev)
    assert 0.0 <= ev["score"] <= 1.0


def test_silence_is_a_resource_the_lead_rests_and_the_foreground_breathes() -> None:
    p = _plan("composed")
    bar = p["bar_s"]
    lead = [e for e in p["events"] if e["hierarchy"] == "lead"]
    for ph in p["phrases"]:
        if ph["bars"] >= 3:
            last = (ph["start_bar"] + ph["bars"] - 1) * bar
            assert not any(last - 1e-6 <= e["t"] < last + bar for e in lead)
    q = evaluate(
        p,
        {t["id"]: np.zeros((int((p["duration_s"] + 2.5) * SR), 2)) for t in p["tracks"]},
        np.zeros((int((p["duration_s"] + 2.5) * SR), 2)),
    )
    assert 0.2 <= q["measured"]["silence_density"]["foreground_silent_step_share"] <= 0.9


@pytest.mark.parametrize("mode", ["organic", "composed"])
def test_at_most_two_foreground_layers_attack_at_once(mode: str) -> None:
    p = _plan(mode)
    fg = [e for e in p["events"] if e["hierarchy"] in ("lead", "foundation", "support", "gesture")]
    for e in fg:  # simultaneous attack windows at the moment each event starts
        now = [o for o in fg if o["t"] <= e["t"] + 1e-9 < o["t"] + min(o["dur"], o["fg_window_s"])]
        assert len(now) <= FOREGROUND_LIMIT


def test_enforce_foreground_drops_the_lowest_priority_first() -> None:
    mk = lambda h, t: {"hierarchy": h, "t": t, "dur": 0.2, "velocity": 0.5, "fg_window_s": 0.2}  # noqa: E731
    evs = [mk("lead", 0.0), mk("foundation", 0.0), mk("support", 0.05), mk("gesture", 0.1)]
    dropped = enforce_foreground(evs)
    assert dropped == 2 and {e["hierarchy"] for e in evs} == {"lead", "foundation"}


# ------------------------------------------------------------------ groove
def test_groove_swing_and_microtiming_are_small_and_bounded() -> None:
    p = analyse_and_plan(three_sources(), seed=4, duration_s=30, mode="composed", groove_q=1.0)[0]
    step = p["bar_s"] / 16
    sw = p["groove"]["swing_steps"]
    off = []
    for e in p["events"]:
        if (
            e["hierarchy"] in ("foundation", "lead")
            and e["motif"]
            and e.get("variation") not in ("fill",)
            and e["kind"] == "slice"
            and "pitch_shift_st" not in e
        ):
            pos = e["t"] / step
            off.append(
                min(abs(pos - round(pos)), abs(pos - round(pos) - sw), abs(pos - round(pos) + sw))
                * step
            )
    assert off and max(off) <= 0.016  # swing (a deliberate offset) + micro-timing within ±14 ms


def test_groove_modes_differ_in_measured_timing() -> None:
    srcs = three_sources()
    src_timed = analyse_and_plan(srcs, seed=4, duration_s=30, mode="composed", groove_q=0.0)[0]
    quantised = analyse_and_plan(srcs, seed=4, duration_s=30, mode="composed", groove_q=1.0)[0]
    hybrid = analyse_and_plan(srcs, seed=4, duration_s=30, mode="composed")[0]

    def off_grid(p) -> float:  # type: ignore[no-untyped-def]
        st = p["bar_s"] / 16
        fg = [e for e in p["events"] if e["hierarchy"] == "foundation"]
        return float(np.mean([abs(e["t"] / st - round(e["t"] / st)) for e in fg]))

    assert off_grid(quantised) < off_grid(hybrid) <= off_grid(src_timed) + 0.05
    assert src_timed["groove"]["quantisation"] == 0.0 and quantised["groove"]["quantisation"] == 1.0


def test_swing_and_ghosts_exist_in_composed_not_organic() -> None:
    c = _plan("composed")
    o = _plan("organic")
    assert c["groove"]["swing_steps"] > 0 and o["groove"]["swing_steps"] == 0
    assert any(e["ghost"] for e in c["events"])
    assert not any(e.get("variation") == "fill" for e in o["events"])
    assert any(e.get("variation") == "fill" for e in c["events"])


# ------------------------------------------------------------------ modes and tonal safety
def test_organic_and_composed_are_measurably_different() -> None:
    o, c = _plan("organic"), _plan("composed")
    fg = lambda p: [e for e in p["events"] if e["hierarchy"] != "bed"]  # noqa: E731
    assert len(fg(c)) > len(fg(o))
    assert o["groove"]["quantisation"] < c["groove"]["quantisation"]
    assert len({ph["bars"] for ph in c["phrases"]}) <= len({ph["bars"] for ph in o["phrases"]}) + 1
    bed = lambda p: np.mean([e["gain_db"] for e in p["events"] if e["hierarchy"] == "bed"])  # noqa: E731
    assert bed(o) > bed(c)  # organic keeps the environment forward
    assert o["ducking"]["depths"] != c["ducking"]["depths"]
    assert not o["conversation"] or len(c["conversation"]) >= 1


def test_noise_and_clicks_never_become_a_melody() -> None:
    srcs = [
        make_source(steady_noise(5.0, 1)),
        make_source(synth.click_train(3.0, SR, 6.0)),
        make_source(steady_noise(5.0, 2)),
    ]
    for mode in ("organic", "composed"):
        p = analyse_and_plan(srcs, seed=2, duration_s=25, mode=mode)[0]
        assert p["key"] is None
        assert all("pitch_shift_st" not in e for e in p["events"])
        assert all(t["role"] != "tonal_motif" for t in p["tracks"])


def test_a_source_is_either_a_bed_or_a_voice_never_both() -> None:
    p = _plan("composed")
    bed_src = {t["source"] for t in p["tracks"] if t["hierarchy"] == "bed"}
    voice_src = {t["source"] for t in p["tracks"] if t["hierarchy"] != "bed"}
    assert bed_src and voice_src and not (bed_src & voice_src)


def test_single_noise_source_still_composes() -> None:
    p = analyse_and_plan([make_source(steady_noise(6.0))], seed=1, duration_s=20, mode="composed")[
        0
    ]
    assert p["events"] and all(e["source_end_s"] > e["source_start_s"] for e in p["events"])


def test_empty_and_oversized_selection_rejected() -> None:
    with pytest.raises(ValueError):
        analyse_and_plan([], seed=1, mode="composed")
    with pytest.raises(ValueError):
        analyse_and_plan(three_sources(), seed=1, mode="jazz")


# ------------------------------------------------------------------ pitch shifting that keeps duration
def test_sola_stretch_changes_length_not_pitch() -> None:
    x = synth.sine(440.0, SR, 0.6, 0.4)
    for n_out in (int(0.45 * SR), int(0.8 * SR)):
        y = sola_stretch(x, n_out)
        assert y.size == n_out and np.isfinite(y).all()
        _, f0, _ = yin_pitch(y[int(0.05 * SR) : -int(0.05 * SR)], SR)
        voiced = f0[f0 > 0]
        assert voiced.size and abs(np.median(voiced) - 440.0) / 440.0 < 0.03


def test_preserve_duration_pitch_shift_keeps_length_and_moves_pitch() -> None:
    src = synth.sine(440.0, SR, 1.0, 0.4)
    buf = np.zeros((SR * 2, 2))
    ev = {
        "kind": "slice",
        "t": 0.0,
        "dur": 0.5,
        "source_start_s": 0.0,
        "source_end_s": 0.5,
        "gain_db": 0.0,
        "rate": 2.0,
        "preserve_duration": True,
        "fade_in_s": 0.005,
        "fade_out_s": 0.02,
    }
    render_event(ev, src, 0.0, 1, buf)
    n = int(np.sum(np.abs(buf[:, 0]) > 1e-6))
    assert abs(n / SR - 0.5) < 0.03  # a plain +12 st resample would be 0.25 s
    _, f0, _ = yin_pitch(buf[int(0.05 * SR) : int(0.45 * SR), 0], SR)
    voiced = f0[f0 > 0]
    assert voiced.size and abs(np.median(voiced) - 880.0) / 880.0 < 0.04


# ------------------------------------------------------------------ renderer compatibility + quality report
@pytest.mark.parametrize("mode", ["organic", "composed"])
def test_composed_modes_render_valid_audio(mode: str) -> None:
    res = compose(three_sources(), seed=6, duration_s=25, mode=mode)
    m = res.metrics
    assert np.isfinite(res.master).all() and m["clipping_ratio"] == 0.0 and m["peak_dbfs"] <= -0.99
    assert float(np.max(np.abs(sum(res.stems.values()) - res.master))) < 1e-9
    assert (
        -26 < m["lufs_approx"] < -12
        and m["empty_sections"] == []
        and m["events_out_of_bounds"] == 0
    )
    assert set(res.stems) == {t["id"] for t in res.plan["tracks"]}
    q = evaluate(res.plan, res.stems, res.master)
    assert q["measured"]["discontinuities"]["click_candidates"] == 0
    assert q["measured"]["silence_density"]["max_simultaneous_foreground"] <= 2
    assert "disclaimer" in q and "artistic" in q["disclaimer"]


def test_quality_report_is_transparent_not_a_single_score() -> None:
    res = compose(three_sources(), seed=6, duration_s=25, mode="composed")
    q = evaluate(res.plan, res.stems, res.master)
    assert {
        "rhythm",
        "motifs",
        "phrases",
        "silence_density",
        "masking",
        "dynamics",
        "sources",
        "discontinuities",
        "repetition",
    } <= set(q["measured"])
    assert not any(k in q for k in ("score", "quality_score", "musicality"))
    assert q["measured"]["sources"]["sources_used"] == q["measured"]["sources"]["sources_in_plan"]


def test_ducking_depth_follows_the_hierarchy() -> None:
    p = _plan("composed")
    d = p["ducking"]
    lead = next(t["id"] for t in p["tracks"] if t["hierarchy"] == "lead")
    fnd = next(t["id"] for t in p["tracks"] if t["hierarchy"] == "foundation")
    assert d["depths"][lead] > d["depths"][fnd] and all(
        t in {x["id"] for x in p["tracks"] if x["hierarchy"] == "bed"} for t in d["targets"]
    )
    plain = copy.deepcopy(p)
    plain["ducking"] = None
    assert plain["ducking"] is None
