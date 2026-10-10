"""Deterministic composition planner (PLANNER_VERSION 1).

``plan_composition`` is a pure function of (source analyses, role decisions, seed, controls,
duration). No global RNG: every random choice comes from a ``numpy`` PCG64 stream derived from
``(seed, purpose-label)`` so call order never matters. Sources are keyed and ordered by their
content hash, independent of database retrieval order or UUIDs.

Form (default grammar, adapted by the audio): INTRODUCTION → DISCOVERY → CONVERGENCE →
RESOLUTION. Section lengths vary with the number of sources and how percussive/steady they
are. Layers enter in a fixed role order (atmosphere first, accents last), and each section
activates a measured subset of layers.

Controls (all 0…1, default 0.5) and what they change:
* density   — fraction of a source's rhythmic hits kept, grain-cloud density, motif note count
* structure — 0 keeps each source's natural micro-timing, 1 snaps events to the 16th grid
* intensity — tempo ±8 %, section dynamics, filter brightness, convergence loudness

Provenance: every event carries ``source`` (content hash), ``source_start_s`` / ``source_end_s``.
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any

import numpy as np

from unheard.music import PLANNER_VERSION
from unheard.music.analysis import Segment, SourceAnalysis, hz_to_midi
from unheard.music.roles import ROLES, RoleDecision

SECTIONS = ("introduction", "discovery", "convergence", "resolution")
SECTION_DB = {"introduction": -6.0, "discovery": -3.0, "convergence": 0.0, "resolution": -5.0}
ROLE_BASE_DB = {
    "texture": -8.0,
    "drone": -8.0,
    "rhythmic_texture": -8.0,
    "percussion": -5.0,
    "tonal_motif": -5.0,
    "accent": -5.0,
    "granular": -12.0,
}
ROLE_REVERB = {
    "texture": 0.10,
    "drone": 0.12,
    "rhythmic_texture": 0.10,
    "percussion": 0.14,
    "tonal_motif": 0.28,
    "accent": 0.35,
    "granular": 0.30,
}
ROLE_LOWPASS = {"drone": 700.0}
PENTATONIC = (0, 3, 5, 7, 10)  # minor pentatonic degrees (semitones above the tonic)
TARGET_SEG_RMS_DB = -24.0
STEPS_PER_BAR = 16
DUCK_DEPTH_DB = 4.0
ATMOSPHERE_ROLES = ("texture", "drone", "granular")
LANE_EDGES_HZ = (0.0, 1200.0, 4500.0, 20000.0)
REGISTER_CEILING_MIDI = 84.0  # ≈ 1 kHz: melodies above this are moved down by octaves (≤ 2)
MAX_SOURCES = 8
MAX_EVENTS = 2400

DEFAULT_CONTROLS = {"density": 0.5, "structure": 0.5, "intensity": 0.5}


def rng_for(seed: int, label: str) -> np.random.Generator:
    h = int.from_bytes(hashlib.sha256(label.encode()).digest()[:8], "big")
    return np.random.Generator(np.random.PCG64(np.random.SeedSequence([seed & 0xFFFFFFFF, h])))


def canonical_plan_hash(plan: dict[str, Any]) -> str:
    def strip(o: Any) -> Any:
        if isinstance(o, dict):
            return {k: strip(v) for k, v in o.items() if k not in ("recording_id", "track_uid")}
        if isinstance(o, list):
            return [strip(v) for v in o]
        return o

    blob = json.dumps(strip(plan), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()


def _fold_bpm(bpm: float) -> float:
    while bpm < 70:
        bpm *= 2
    while bpm > 140:
        bpm /= 2
    return bpm


def choose_tempo(
    analyses: list[SourceAnalysis], roles: dict[str, RoleDecision]
) -> tuple[float, str]:
    cands: list[tuple[float, float]] = []
    for a in analyses:
        if a.period_s is not None and a.periodicity >= 0.25:
            cands.append((a.periodicity, _fold_bpm(60.0 / a.period_s)))
    if cands:
        cands.sort(key=lambda t: (-t[0], t[1]))
        return round(cands[0][1], 2), "periodicity"
    iois: list[float] = []
    for a in analyses:
        t = a.onset_times
        iois += [t[i + 1] - t[i] for i in range(len(t) - 1) if t[i + 1] - t[i] > 0.12]
    if len(iois) >= 3:
        return round(_fold_bpm(60.0 / float(np.median(iois))), 2), "onset_intervals"
    return 84.0, "default_free"


def _section_bars(total: int, n_src: int, perc: float, stable: float) -> list[int]:
    w = np.array([0.20, 0.26 + 0.015 * min(n_src, 6), 0.30 + 0.10 * perc, 0.20 + 0.06 * stable])
    w = w / w.sum()
    bars = np.maximum(2, np.round(w * total).astype(int))
    while bars.sum() > total:
        bars[int(np.argmax(bars))] -= 1
    while bars.sum() < total:
        bars[2] += 1
    return [int(b) for b in bars]


def lane_band(rank: int, n: int, edges: tuple[float, ...]) -> tuple[float | None, float | None]:
    """(highpass, lowpass) for the ``rank``-th (0 = darkest) of ``n`` atmosphere layers."""
    k = min(rank, len(edges) - 2)
    if n > len(edges) - 1:  # more layers than lanes: share the top lane
        k = min(rank, len(edges) - 2)
    lo, hi = edges[k], edges[k + 1]
    return (None if lo <= 0 else lo, None if hi >= 20000 else hi)


def _scale_tones(tonic_midi: float) -> list[float]:
    base = int(round(tonic_midi))
    return [float(base + 12 * o + d) for o in range(-8, 9) for d in PENTATONIC]


def _nearest_tone(m: float, tones: list[float]) -> float:
    return min(tones, key=lambda t: (abs(t - m), t))


def plan_composition(
    analyses: list[SourceAnalysis],
    roles: dict[str, RoleDecision],
    *,
    seed: int,
    controls: dict[str, float] | None = None,
    duration_s: float = 45.0,
) -> dict[str, Any]:
    c: dict[str, float] = dict(DEFAULT_CONTROLS)
    c.update(controls or {})
    for k in c:
        c[k] = float(min(1.0, max(0.0, c[k])))
    if not analyses:
        raise ValueError("at least one source is required")
    if len(analyses) > MAX_SOURCES:
        raise ValueError(f"at most {MAX_SOURCES} sources")
    duration_s = float(min(90.0, max(15.0, duration_s)))
    analyses = sorted(analyses, key=lambda a: a.key)

    base_bpm, tempo_src = choose_tempo(analyses, roles)
    bpm = round(base_bpm * (0.92 + 0.16 * c["intensity"]), 2)
    beat_s = 60.0 / bpm
    bar_s = 4 * beat_s
    step_s = bar_s / STEPS_PER_BAR
    total_bars = max(8, int(round(duration_s / bar_s)))
    perc = float(np.mean([roles[a.key].scores["percussion"] for a in analyses]))
    stable = float(np.mean([a.stability for a in analyses]))
    sec_bars = _section_bars(total_bars, len(analyses), perc, stable)
    sections: list[dict[str, Any]] = []
    cur = 0
    for name, nb in zip(SECTIONS, sec_bars, strict=True):
        sections.append(
            {
                "name": name,
                "start_bar": cur,
                "bars": nb,
                "start_s": cur * bar_s,
                "end_s": (cur + nb) * bar_s,
            }
        )
        cur += nb
    total_s = total_bars * bar_s

    # ---- layers: (source, role) pairs, with rebalancing so rhythm and atmosphere exist
    layers: list[tuple[str, str]] = []
    for a in analyses:
        d = roles[a.key]
        layers.append((a.key, d.primary))
        if d.secondary and len(analyses) <= 3:
            layers.append((a.key, d.secondary))
    prio = {r: i for i, r in enumerate(ROLES)}
    by_key = {a.key: a for a in analyses}
    layers.sort(key=lambda kr: (prio[kr[1]], -by_key[kr[0]].stability, kr[0]))
    layers = layers[:10]

    # key from the strongest tonal source
    tonic: float | None = None
    for a in analyses:
        if any(r == "tonal_motif" for k, r in layers if k == a.key) and a.f0_median_hz:
            tonic = hz_to_midi(a.f0_median_hz)
            break
    tones = _scale_tones(tonic) if tonic is not None else []

    # Spectral lanes: atmosphere layers (texture/drone/granular) share the spectrum, so each gets
    # its own band, ordered by measured centroid, and extra layers are tucked down 3 dB each.
    atmos = sorted(
        [i for i, (_k, r) in enumerate(layers) if r in ATMOSPHERE_ROLES],
        key=lambda i: (by_key[layers[i][0]].centroid_median_hz, i),
    )
    lanes: dict[int, tuple[float | None, float | None, float]] = {}
    if len(atmos) >= 2:
        edges = LANE_EDGES_HZ[: len(atmos) + 1] if len(atmos) <= 3 else LANE_EDGES_HZ
        for rank, i in enumerate(atmos):
            lo, hi = lane_band(rank, len(atmos), edges)
            lanes[i] = (lo, hi, -3.0 * rank)

    n_layers = len(layers)
    active_n: dict[str, int] = {
        "introduction": 1,
        "discovery": 1 + math.ceil((n_layers - 1) / 2) if n_layers > 1 else 1,
        "convergence": n_layers,
        "resolution": min(n_layers, 2 if n_layers > 2 else 1),
    }
    intens_db = (c["intensity"] - 0.5) * 6.0

    tracks: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    for li, (key, role) in enumerate(layers):
        a = by_key[key]
        tid = f"t{li + 1}"
        pan = float(np.clip(((li % 5) - 2) * 0.28 * (1 if li % 2 == 0 else -1), -0.7, 0.7))
        if role in ("drone", "texture"):
            pan *= 0.4
        if role == "percussion":
            pan *= 0.5
        track = {
            "id": tid,
            "source": key,
            "role": role,
            "layer_order": li,
            "pan": round(pan, 3),
            "reverb_send": ROLE_REVERB[role],
            "base_gain_db": ROLE_BASE_DB[role],
            "enters": next(
                (s["name"] for s in sections if li < active_n[s["name"]]), "convergence"
            ),
        }
        tracks.append(track)
        rng = rng_for(seed, f"{key}:{role}:{li}")
        evs: list[dict[str, Any]] = []
        for si, sec in enumerate(sections):
            if li >= active_n[sec["name"]]:
                continue
            # fewer layers sound quieter: give thin sections +1.5 dB per missing layer (≤ +6 dB)
            thin = min(6.0, 1.5 * (n_layers - active_n[sec["name"]]))
            sec_db = (
                SECTION_DB[sec["name"]]
                + thin
                + (intens_db if sec["name"] == "convergence" else 0.4 * intens_db)
            )
            evs += _role_events(
                role,
                a,
                sec,
                si,
                bar_s,
                beat_s,
                step_s,
                c,
                tones,
                rng,
                sec_db,
                li,
                bpm,
                lanes.get(li),
            )
        for e in evs:
            e.update(track=tid, source=key, role=role)
        events += evs
    if len(events) > MAX_EVENTS:
        events = events[:MAX_EVENTS]
    # Atmosphere layers step aside (−DUCK_DEPTH_DB) for hits, accents and notes, so beds do not
    # mask them. Recorded in the plan; applied by the renderer on the stems (sum is preserved).
    ducking = {
        "depth_db": DUCK_DEPTH_DB,
        "attack_s": 0.015,
        "release_s": 0.25,
        "max_hold_s": 0.4,
        "targets": [t["id"] for t in tracks if t["role"] in ATMOSPHERE_ROLES],
        "triggers": [
            t["id"] for t in tracks if t["role"] in ("percussion", "accent", "tonal_motif")
        ],
    }
    events.sort(key=lambda e: (e["t"], e["track"], e["kind"]))
    for i, e in enumerate(events):
        e["seq"] = i
        e["t"] = round(float(e["t"]), 5)
        e["dur"] = round(float(e["dur"]), 5)

    return {
        "planner_version": PLANNER_VERSION,
        "seed": int(seed),
        "controls": c,
        "tempo_bpm": bpm,
        "tempo_source": tempo_src,
        "time_signature": "4/4",
        "key": None
        if tonic is None
        else {
            "tonic_midi": round(tonic, 3),
            "scale": "minor_pentatonic",
            "from": "measured f0 median",
        },
        "duration_s": round(total_s, 4),
        "tail_s": 2.5,
        "bar_s": round(bar_s, 5),
        "sections": [
            {**s, "start_s": round(s["start_s"], 4), "end_s": round(s["end_s"], 4)}
            for s in sections
        ],
        "tracks": tracks,
        "ducking": ducking,
        "events": events,
        "sources": [a.key for a in analyses],
    }


def _gain(a: SourceAnalysis, seg: Segment, role: str, sec_db: float, extra: float = 0.0) -> float:
    # mild loudness compensation toward a common level, never full normalisation
    seg_db = a.rms_dbfs  # whole-clip RMS: stable proxy; per-window RMS is applied in render
    comp = float(np.clip(0.6 * (TARGET_SEG_RMS_DB - seg_db), -12.0, 12.0))
    del seg
    return round(ROLE_BASE_DB[role] + comp + sec_db + extra, 2)


def _fade(dur: float, frac: float = 0.25, lo: float = 0.008, hi: float = 0.6) -> float:
    return round(float(min(hi, max(lo, dur * frac))), 4)


def _role_events(
    role: str,
    a: SourceAnalysis,
    sec: dict[str, Any],
    si: int,
    bar_s: float,
    beat_s: float,
    step_s: float,
    c: dict[str, float],
    tones: list[float],
    rng: np.random.Generator,
    sec_db: float,
    li: int,
    bpm: float,
    lane: tuple[float | None, float | None, float] | None = None,
) -> list[dict[str, Any]]:
    t0, t1 = sec["start_s"], sec["end_s"]
    out: list[dict[str, Any]] = []
    if lane is not None:
        sec_db += lane[2]
    bright = 1800.0 + 7000.0 * (0.25 * si / 3 + 0.75 * c["intensity"]) if si < 3 else 2600.0

    if role in ("texture", "drone"):
        seg = a.sustained
        if seg is None:
            return out
        fade = 1.2
        start = max(0.0, t0 - fade / 2)
        end = t1 + fade / 2
        rate = 0.5 if role == "drone" else 1.0
        lp = ROLE_LOWPASS.get(role, bright)
        out.append(
            {
                "kind": "loop",
                "t": start,
                "dur": end - start,
                "section": sec["name"],
                "source_start_s": seg.start_s,
                "source_end_s": seg.end_s,
                "gain_db": _gain(a, seg, role, sec_db),
                "rate": rate,
                "lowpass_hz": round(lp, 1),
                "fade_in_s": fade,
                "fade_out_s": fade,
                "crossfade_s": 0.9,
            }
        )
    elif role == "rhythmic_texture":
        seg = a.sustained
        if seg is None or a.period_s is None:
            return out
        cycle = a.period_s
        every = 1 if bpm < 100 else 2  # beats between cycle starts
        rate = float(np.clip(cycle / (every * beat_s), 0.7, 1.4)) if c["structure"] > 0.3 else 1.0
        src_len = min(cycle, seg.end_s - seg.start_s)
        n_beats = int(round((t1 - t0) / beat_s))
        for b in range(0, n_beats, every):
            tt = t0 + b * beat_s
            ss = seg.start_s + (b // every % 2) * 0.0
            out.append(
                {
                    "kind": "slice",
                    "t": tt,
                    "dur": src_len / rate,
                    "section": sec["name"],
                    "source_start_s": ss,
                    "source_end_s": ss + src_len,
                    "gain_db": _gain(a, seg, role, sec_db),
                    "rate": round(rate, 4),
                    "lowpass_hz": round(bright, 1),
                    "fade_in_s": 0.02,
                    "fade_out_s": 0.04,
                }
            )
    elif role in ("percussion", "accent"):
        if not a.transients:
            return out
        hits = _rhythm_pattern(a, bar_s, step_s, c["structure"])
        keep = 0.35 + 0.65 * c["density"]
        keep *= {"introduction": 0.5, "discovery": 0.8, "convergence": 1.0, "resolution": 0.5}[
            sec["name"]
        ]
        if role == "accent":
            # transition accents: one strong hit at each section boundary after the first
            if si == 0:
                return out
            seg = a.transients[0]
            out.append(
                {
                    "kind": "slice",
                    "t": t0,
                    "dur": (seg.end_s - seg.start_s) * 1.6,
                    "section": sec["name"],
                    "source_start_s": seg.start_s,
                    "source_end_s": seg.end_s,
                    "gain_db": _gain(a, seg, role, sec_db),
                    "rate": 0.8,
                    "lowpass_hz": 9000.0,
                    "fade_in_s": 0.004,
                    "fade_out_s": 0.08,
                }
            )
            return out
        n_pat = max(1, hits["bars"])
        for bar in range(sec["bars"]):
            pat = hits["bar_hits"][(sec["start_bar"] + bar) % n_pat]
            ranked = sorted(pat, key=lambda h: (-h["strength"], h["step"]))
            kept = (
                {id(h) for h in ranked[: max(1, int(round(len(ranked) * keep)))]}
                if ranked
                else set()
            )
            for h in pat:
                if id(h) not in kept:
                    continue
                seg = h["seg"]
                tt = t0 + bar * bar_s + h["step"] * step_s
                if tt >= t1:
                    continue
                out.append(
                    {
                        "kind": "slice",
                        "t": tt,
                        "dur": min(seg.end_s - seg.start_s, t1 - tt + 0.2),
                        "section": sec["name"],
                        "source_start_s": seg.start_s,
                        "source_end_s": min(seg.end_s, seg.start_s + (t1 - tt + 0.2)),
                        "gain_db": _gain(
                            a, seg, role, sec_db, extra=-3.0 + 3.0 * min(1.0, h["strength"] / 12.0)
                        ),
                        "rate": 1.0,
                        "lowpass_hz": 12000.0,
                        "fade_in_s": 0.002,
                        "fade_out_s": 0.03,
                    }
                )
    elif role == "tonal_motif":
        runs = a.voiced_runs
        if not runs or not tones:
            return out
        n_notes = 3 + int(round(5 * c["density"]))
        order = sorted(runs[:8], key=lambda r: r.start_s)
        motif: list[dict[str, Any]] = []
        for k in range(n_notes):
            r = order[k % len(order)]
            m = r.meta["midi"]
            target = _nearest_tone(m, tones)
            if k % 4 == 3:  # cadence step: next scale tone up
                idx = tones.index(target)
                target = tones[min(len(tones) - 1, idx + 1)]
            shift = float(np.clip(target - m, -7.0, 7.0))
            octaves = int(min(2, max(0, math.ceil((m + shift - REGISTER_CEILING_MIDI) / 12.0))))
            beats = 1.0 if k % 2 == 0 else (2.0 if rng.random() < 0.5 else 1.0)
            motif.append({"seg": r, "shift": shift, "octaves": octaves, "beats": beats})
        phrase_beats = sum(n["beats"] for n in motif)
        phrase_beats = max(4.0, math.ceil(phrase_beats / 4.0) * 4.0)
        pos = t0 + (0.0 if si != 0 else 0.0)
        rep = 0
        while pos < t1 - beat_s:
            seq = motif if rep % 2 == 0 else list(reversed(motif))
            tb = 0.0
            for n in seq:
                tt = pos + tb * beat_s
                tb += n["beats"]
                if tt >= t1 - 0.05:
                    break
                r = n["seg"]
                total_st = n["shift"] - 12.0 * n["octaves"]
                rate = 2.0 ** (total_st / 12.0)
                dur = min((r.end_s - r.start_s) / rate, n["beats"] * beat_s * 1.5)
                out.append(
                    {
                        "kind": "slice",
                        "t": tt,
                        "dur": dur,
                        "section": sec["name"],
                        "source_start_s": r.start_s,
                        "source_end_s": min(r.end_s, r.start_s + dur * rate),
                        "gain_db": _gain(a, r, role, sec_db),
                        "rate": round(rate, 5),
                        "pitch_shift_st": round(total_st, 3),
                        "octave_shift": -n["octaves"],
                        "lowpass_hz": 10000.0,
                        "fade_in_s": 0.01,
                        "fade_out_s": _fade(dur, 0.35),
                    }
                )
            pos += phrase_beats * beat_s
            rep += 1
            if sec["name"] in ("introduction", "resolution"):
                pos += phrase_beats * beat_s  # sparser phrasing
    elif role == "granular":
        seg = a.sustained or (a.transients[0] if a.transients else None)
        if seg is None:
            return out
        dens = 6.0 + 22.0 * c["density"]
        out.append(
            {
                "kind": "grains",
                "t": t0,
                "dur": t1 - t0,
                "section": sec["name"],
                "source_start_s": seg.start_s,
                "source_end_s": seg.end_s,
                "gain_db": _gain(a, seg, role, sec_db),
                "rate": 1.0,
                "grain_density_hz": round(dens, 2),
                "grain_s": 0.09,
                "pitch_jitter_st": 3.0,
                "grain_seed": int(rng.integers(0, 2**31 - 1)),
                "lowpass_hz": round(bright, 1),
                "fade_in_s": 1.0,
                "fade_out_s": 1.0,
            }
        )
    if lane is not None:
        for e in out:
            if lane[0] is not None:
                e["highpass_hz"] = lane[0]
            if lane[1] is not None:
                e["lowpass_hz"] = round(min(float(e.get("lowpass_hz", 20000.0)), lane[1]), 1)
    return out


def _rhythm_pattern(
    a: SourceAnalysis, bar_s: float, step_s: float, structure: float
) -> dict[str, Any]:
    """Map the source's real onset sequence onto the bar grid (compress/stretch the pattern, not audio)."""
    ons = sorted(a.transients, key=lambda s: s.meta["onset_s"])
    times = np.array([s.meta["onset_s"] for s in ons])
    span = float(times[-1] - times[0]) if times.size > 1 else 0.0
    n_bars = max(1, int(round(span / max(bar_s, 1e-6)))) if span > 0 else 1
    n_bars = min(n_bars, 4)
    pat_len = n_bars * bar_s
    hits_by_bar: list[list[dict[str, Any]]] = [[] for _ in range(n_bars)]
    for s, t in zip(ons, times, strict=True):
        rel = (t - times[0]) / (span if span > 0 else 1.0) * (pat_len - step_s)
        pos = rel / step_s  # in 16th steps over the whole pattern
        quant = float(round(pos))
        pos = (1.0 - structure) * pos + structure * quant
        bar = min(n_bars - 1, int(pos // STEPS_PER_BAR))
        step = float(pos - bar * STEPS_PER_BAR)
        hits_by_bar[bar].append({"seg": s, "step": step, "strength": s.score})
    return {"bars": n_bars, "bar_hits": hits_by_bar}
