"""Transparent composition diagnostics (M4.6).

Everything returned here is an *objective measurement* of a plan and its rendered audio. None of it is a
score of musical beauty, and no number here is combined into one. The purpose is to catch technical
and structural weaknesses (buried foreground, literal repetition, no silence, masking, clicks); a human
listening session remains the only artistic gate.

Measured groups: motif recurrence/variation, rhythmic diversity, phrase structure, silence and
density, foreground clarity, spectral masking, dynamic development, source contribution, audible
discontinuities, repetition fatigue.
"""

from __future__ import annotations

from itertools import combinations
from typing import Any

import numpy as np
from numpy.typing import NDArray
from scipy import signal

SR = 48_000
BANDS = [(20, 250), (250, 1000), (1000, 4000), (4000, 8000), (8000, 20000)]
FG_ROLES = ("percussion", "tonal_motif", "accent", "rhythmic_texture")

DISCLAIMER = (
    "Objective measurements of the plan and the rendered audio only. They detect technical and structural "
    "weaknesses; they cannot show that a piece sounds good. Human listening is the final artistic gate."
)


def _is_fg(e: dict[str, Any], role_of: dict[str, str]) -> bool:
    h = e.get("hierarchy")
    if h is not None:
        return h in ("lead", "foundation", "support", "gesture")
    return role_of.get(e["track"], e.get("role", "")) in FG_ROLES and e["kind"] == "slice"


def _entropy(counts: NDArray[np.float64]) -> float:
    p = counts / max(counts.sum(), 1e-12)
    p = p[p > 0]
    return float(-(p * np.log(p)).sum() / np.log(len(counts))) if len(counts) > 1 else 0.0


def evaluate(
    plan: dict[str, Any], stems: dict[str, NDArray[np.float64]], master: NDArray[np.float64]
) -> dict[str, Any]:
    ev = plan["events"]
    role_of = {t["id"]: t["role"] for t in plan["tracks"]}
    bar_s = plan["bar_s"]
    step_s = bar_s / 16
    n_bars = int(round(plan["duration_s"] / bar_s))
    fg = [e for e in ev if _is_fg(e, role_of)]
    m: dict[str, Any] = {"mode": plan.get("mode", "legacy")}

    # ---- rhythmic diversity + literal repetition (bar signatures from the plan) -----------------
    sigs: list[frozenset[tuple[str, int]]] = []
    occupancy = np.zeros(16)
    for b in range(n_bars):
        in_bar = [e for e in fg if b * bar_s - 1e-6 <= e["t"] < (b + 1) * bar_s - 1e-6]
        sig = frozenset(
            (e["source"], int(round((e["t"] - b * bar_s) / step_s)) % 16) for e in in_bar
        )
        sigs.append(sig)
        for _, st in sig:
            occupancy[st] += 1
    nonempty = [s for s in sigs if s]
    seen: set[frozenset[tuple[str, int]]] = set()
    literal = 0
    for s in nonempty:
        if s in seen:
            literal += 1
        seen.add(s)
    run = best_run = 0
    for i in range(1, len(sigs)):
        run = run + 1 if sigs[i] and sigs[i] == sigs[i - 1] else 0
        best_run = max(best_run, run)
    m["rhythm"] = {
        "foreground_events": len(fg),
        "foreground_events_per_bar": round(len(fg) / max(n_bars, 1), 2),
        "distinct_bar_patterns": len(seen),
        "bars_with_foreground": len(nonempty),
        "literal_bar_repeat_ratio": round(literal / max(len(nonempty), 1), 3),
        "longest_identical_bar_run": best_run + 1 if best_run else 0,
        "step_occupancy_entropy": round(_entropy(occupancy), 3),
        "off_grid_share": round(
            float(np.mean([abs((e["t"] / step_s) - round(e["t"] / step_s)) > 0.12 for e in fg])), 3
        )
        if fg
        else 0.0,
    }

    # ---- motifs and phrases (composer plans only) --------------------------------------------
    if plan.get("motifs") is not None:
        inst = [e for e in fg if e.get("motif")]
        variants = [
            e for e in inst if e.get("variation") not in (None, "boundary", "response", "fill")
        ]
        base = [e for e in inst if e.get("variation") is None]
        motif_ids = {e["motif"] for e in inst}
        relations = [mo["relation"]["operator"] for mo in plan["motifs"] if mo.get("relation")]
        phrases = plan.get("phrases", [])
        lens = [p["bars"] for p in phrases]
        lead_ev = [e for e in ev if e.get("hierarchy") == "lead"]
        rests = 0
        for p in phrases:
            end_bar = p["start_bar"] + p["bars"]
            if p["bars"] >= 3 and not any(
                (end_bar - 1) * bar_s - 1e-6 <= e["t"] < end_bar * bar_s for e in lead_ev
            ):
                rests += 1
        long_phr = [p for p in phrases if p["bars"] >= 3]
        m["motifs"] = {
            "distinct_motifs_sounding": len(motif_ids),
            "variant_operators": sorted(set(relations)),
            "base_motif_events": len(base),
            "variation_events": len(variants),
            "variation_share": round(len(variants) / max(len(inst), 1), 3),
            "form": plan.get("form"),
            "conversation_pairs": len(plan.get("conversation", [])),
        }
        m["phrases"] = {
            "count": len(phrases),
            "lengths_bars": sorted(set(lens)),
            "irregular": len(set(lens)) > 1,
            "phrases_with_lead_rest_bar": rests,
            "long_phrases": len(long_phr),
        }

    # ---- silence / density / foreground clarity ----------------------------------------------
    total_steps = n_bars * 16
    occ = np.zeros(total_steps, bool)
    for e in fg:
        s0 = int(e["t"] / step_s)
        s1 = int((e["t"] + min(e["dur"], e.get("fg_window_s", 0.25))) / step_s)
        occ[max(0, s0) : min(total_steps, s1 + 1)] = True
    mono = master.mean(axis=1)
    blk = int(0.1 * SR)
    nb = len(mono) // blk
    rms_blocks = (
        np.sqrt(np.mean(mono[: nb * blk].reshape(nb, blk) ** 2, axis=1)) if nb else np.zeros(1)
    )
    pts = sorted(((e["t"], 1) for e in fg), key=lambda p: p[0])
    edges: list[tuple[float, int]] = []
    for e in fg:
        edges += [(e["t"], 1), (e["t"] + min(e["dur"], e.get("fg_window_s", 0.25)), -1)]
    edges.sort()
    cur = peak = 0
    over_time = 0.0
    last_t = 0.0
    for t, d in edges:
        if cur > 2:
            over_time += t - last_t
        cur += d
        peak = max(peak, cur)
        last_t = t
    del pts
    m["silence_density"] = {
        "foreground_silent_step_share": round(1.0 - float(occ.mean()), 3),
        "audio_silence_share_below_-60dBFS": round(
            float(np.mean(rms_blocks < 10 ** (-60 / 20))), 3
        ),
        "max_simultaneous_foreground": int(peak),
        "time_with_more_than_2_foreground_s": round(over_time, 2),
    }

    # ---- spectral masking and per-event clarity ---------------------------------------------
    names = list(stems)
    f_ax = np.fft.rfftfreq(2048, 1 / SR)

    def band_energy(x: NDArray[np.float64]) -> NDArray[np.float64]:
        _, _, z = signal.stft(x, SR, nperseg=2048, noverlap=1536)
        p = np.abs(z) ** 2
        return np.stack(
            [p[(f_ax[: p.shape[0]] >= lo) & (f_ax[: p.shape[0]] < hi)].sum(0) for lo, hi in BANDS]
        )

    mono_stems = {k: v.mean(axis=1) for k, v in stems.items()}
    be = {k: band_energy(v) for k, v in mono_stems.items()}
    frames = min(b.shape[1] for b in be.values())
    act = {k: be[k][:, :frames].sum(0) for k in be}
    live = {
        k: act[k] > max(np.percentile(act[k], 5) * 4, 1e-9 * float(act[k].max()) + 1e-14)
        for k in act
    }
    overlaps = []
    for na, nb_ in combinations(names, 2):
        both = live[na] & live[nb_]
        if both.sum() < 20:
            continue
        pa, pb = be[na][:, :frames][:, both].sum(1), be[nb_][:, :frames][:, both].sum(1)
        overlaps.append(float(np.minimum(pa / pa.sum(), pb / pb.sum()).sum()))
    clar: dict[str, float] = {}
    for tr in plan["tracks"]:
        if tr["id"] not in stems:
            continue
        vals = []
        for e in (x for x in fg if x["track"] == tr["id"]):
            a0, a1 = int(e["t"] * SR), int((e["t"] + min(e["dur"], 0.3)) * SR)
            own = float(np.sum(mono_stems[tr["id"]][a0:a1] ** 2)) + 1e-12
            oth = (
                sum(float(np.sum(v[a0:a1] ** 2)) for k, v in mono_stems.items() if k != tr["id"])
                + 1e-12
            )
            vals.append(10 * np.log10(own / oth))
        if vals:
            clar[tr["id"]] = round(float(np.median(vals)), 1)
    m["masking"] = {
        "mean_stem_spectral_overlap": round(float(np.mean(overlaps)), 3) if overlaps else None,
        "worst_stem_pair_overlap": round(float(max(overlaps)), 3) if overlaps else None,
        "median_event_clarity_db_by_track": clar,
    }

    # ---- dynamic development ------------------------------------------------------------------
    secs = []
    for s in plan["sections"]:
        seg = master[int(s["start_s"] * SR) : int(s["end_s"] * SR)]
        secs.append(
            {
                "section": s["name"],
                "rms_dbfs": round(float(20 * np.log10(max(np.sqrt(np.mean(seg**2)), 1e-9))), 1),
            }
        )
    rms = [s["rms_dbfs"] for s in secs]
    m["dynamics"] = {
        "section_rms": secs,
        "spread_db": round(max(rms) - min(rms), 1),
        "climax_in_convergence": bool(rms[2] >= max(rms) - 0.5),
        "convergence_over_ends_db": [round(rms[2] - rms[0], 1), round(rms[2] - rms[3], 1)],
    }

    # ---- source contribution ------------------------------------------------------------------
    by_src_rms: dict[str, float] = {}
    by_src_ev: dict[str, int] = {}
    src_of = {t["id"]: t["source"] for t in plan["tracks"]}
    for k, v in mono_stems.items():
        by_src_rms[src_of[k]] = by_src_rms.get(src_of[k], 0.0) + float(np.sqrt(np.mean(v**2)))
    for e in ev:
        by_src_ev[e["source"]] = by_src_ev.get(e["source"], 0) + 1
    tot = sum(by_src_rms.values()) or 1.0
    shares = {k[:8]: round(v / tot, 3) for k, v in by_src_rms.items()}
    m["sources"] = {
        "audio_share": shares,
        "events": {k[:8]: v for k, v in by_src_ev.items()},
        "sources_in_plan": len(plan["sources"]),
        "sources_used": len(by_src_ev),
        "min_audio_share": round(min(shares.values()), 3) if shares else 0.0,
    }

    # ---- audible discontinuities --------------------------------------------------------------
    d2 = np.abs(np.diff(mono, 2))
    w = int(0.005 * SR)
    c = np.cumsum(np.concatenate([[0.0], mono**2]))
    local = np.sqrt(np.maximum((c[2 * w :] - c[: -2 * w]) / (2 * w), 1e-12))[: d2.size]
    n = min(d2.size, local.size)
    clicks = int(np.sum((d2[:n] > 0.2) & (d2[:n] > 14 * local[:n])))
    m["discontinuities"] = {
        "max_second_difference": round(float(d2.max()), 3) if d2.size else 0.0,
        "click_candidates": clicks,
        "peak_dbfs": round(float(20 * np.log10(max(np.abs(master).max(), 1e-9))), 2),
    }

    # ---- repetition fatigue -------------------------------------------------------------------
    frag_use: dict[tuple[str, float, float], int] = {}
    for e in fg:
        k2 = (e["source"], round(e["source_start_s"], 3), round(e["source_end_s"], 3))
        frag_use[k2] = frag_use.get(k2, 0) + 1
    prof = []
    f2, t2, z2 = signal.stft(mono, SR, nperseg=2048, noverlap=1536)
    p2 = np.abs(z2) ** 2
    for b in range(n_bars):
        sel = (t2 >= b * bar_s) & (t2 < (b + 1) * bar_s)
        v = np.log10(
            np.array([p2[(f2 >= lo) & (f2 < hi)][:, sel].sum() for lo, hi in BANDS]) + 1e-12
        )
        prof.append(v - v.mean())
    sims = [
        float(
            np.dot(prof[i], prof[i + 1])
            / (np.linalg.norm(prof[i]) * np.linalg.norm(prof[i + 1]) + 1e-12)
        )
        for i in range(len(prof) - 1)
    ]
    m["repetition"] = {
        "adjacent_bar_spectral_similarity": round(float(np.mean(sims)), 3) if sims else None,
        "distinct_fragment_windows": len(frag_use),
        "most_reused_fragment_count": max(frag_use.values()) if frag_use else 0,
    }

    # ---- flags (thresholds are documented guesses, not truths) ---------------------------------
    flags: list[str] = []
    r = m["rhythm"]
    if r["literal_bar_repeat_ratio"] > 0.5:
        flags.append(
            f"REPETITION: {r['literal_bar_repeat_ratio']:.0%} of bars with foreground repeat an earlier bar exactly"
        )
    if r["longest_identical_bar_run"] >= 4:
        flags.append(f"REPETITION: {r['longest_identical_bar_run']} identical bars in a row")
    sd = m["silence_density"]
    if sd["max_simultaneous_foreground"] > 2 and sd["time_with_more_than_2_foreground_s"] > 0.5:
        flags.append("FOREGROUND: more than two attacks compete for the foreground")
    if sd["foreground_silent_step_share"] < 0.25:
        flags.append("DENSITY: foreground is almost never silent (little air)")
    if (
        m["masking"]["median_event_clarity_db_by_track"]
        and min(m["masking"]["median_event_clarity_db_by_track"].values()) < -3
    ):
        flags.append("CLARITY: some foreground events sit > 3 dB under the other layers")
    if m["dynamics"]["spread_db"] > 15:
        flags.append("DYNAMICS: section loudness spread > 15 dB")
    if not m["dynamics"]["climax_in_convergence"]:
        flags.append("DEVELOPMENT: loudest section is not the convergence")
    if m["sources"]["sources_used"] < m["sources"]["sources_in_plan"]:
        flags.append("SOURCES: some selected recordings contribute nothing")
    if m["discontinuities"]["click_candidates"] > 0:
        flags.append(f"CLICKS: {m['discontinuities']['click_candidates']} click candidate(s)")
    if m["repetition"]["most_reused_fragment_count"] > 20:
        flags.append("FATIGUE: one fragment is reused more than 20 times")
    return {
        "measured": m,
        "flags": flags or ["no technical or structural weakness flagged by these proxies"],
        "disclaimer": DISCLAIMER,
    }
