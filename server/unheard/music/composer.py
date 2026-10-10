"""Motif/phrase composer (COMPOSER_VERSION 2, M4.6).

``source recording → material (fragments) → motif → phrase → section → composition``

The legacy planner (planner.py) scheduled *events*; this composer builds *musical sentences* out of
the same real recordings. Everything remains a deterministic function of (analyses, material, seed,
controls, duration, mode); all randomness comes from ``rng_for(seed, label)`` streams.

Layers carry a hierarchy so that every moment has a clear foreground:

* lead        — the motif the listener follows (tonal if a reliable pitched source exists, else rhythmic)
* foundation  — the groove (a different source if possible)
* support     — answers the lead in its rests (call-and-response); never speaks over it
* gesture     — one distinctive fragment marking section boundaries
* bed         — sustained atmosphere: quiet, band-limited, ducked under foreground, with air gaps

At most two foreground layers (lead, foundation, support, gesture) have an attack sounding at the same
time; `enforce_foreground` guarantees it and drops the lowest-priority events when needed.

Motif variation always has a documented relationship to its parent (`relation`): shift (syncopation),
density (drop weakest / add ghost notes), fragment swap (another real fragment of the same source,
same positions), register (octave), retrograde (tonal), answer (question half). The two modes:

* ORGANIC  — source-timed groove (little quantisation), no swing, 10 ms micro-timing, irregular phrase
             lengths (3–5 bars), prominent soft beds, short subtle lead, sparse foundation, no fills,
             no scheduled conversation (a single response in the convergence).
* COMPOSED — hybrid groove (≈60 % toward the 16th grid) with swing, accents, ghost notes, 5 ms
             micro-timing, fixed 4-bar phrases, clear A / A' / B / A'' form, fills before phrase ends,
             scheduled call-and-response, quieter beds with gaps and strong ducking.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Any

import numpy as np

from unheard.music import COMPOSER_VERSION
from unheard.music.analysis import SourceAnalysis
from unheard.music.material import Fragment, Material
from unheard.music.planner import (
    ATMOSPHERE_ROLES,
    LANE_EDGES_HZ,
    MAX_EVENTS,
    MAX_SOURCES,
    STEPS_PER_BAR,
    choose_tempo,
    lane_band,
    rng_for,
)
from unheard.music.roles import RoleDecision

MODES = ("organic", "composed")
FOREGROUND = ("lead", "foundation", "support", "gesture")
FOREGROUND_LIMIT = 2
PRIORITY = {"lead": 0, "foundation": 1, "gesture": 2, "support": 3}
SECTIONS = ("introduction", "discovery", "convergence", "resolution")
ACCENT = {0: 1.0, 8: 0.9, 4: 0.78, 12: 0.78}  # metrical weights; 8th offbeats 0.62; 16ths 0.5
TARGET_RMS_DB = -24.0
REGISTER_LOW, REGISTER_HIGH = (
    52.0,
    90.0,
)  # E3 … F#6 (≈165 Hz–1.5 kHz): a melody is moved by whole octaves only when outside


def register_octaves(center_midi: float) -> int:
    """Whole octaves needed to bring a tonal centre into [REGISTER_LOW, REGISTER_HIGH] (0 if already inside)."""
    o = 0
    while center_midi + 12 * o > REGISTER_HIGH:
        o -= 1
    while center_midi + 12 * o < REGISTER_LOW:
        o += 1
    return o


@dataclass(frozen=True)
class ModeSpec:
    name: str
    quant_base: float  # groove quantisation 0 = source-timed … 1 = on the grid
    quant_span: float  # + span × the "structure" control
    swing: float  # delay of odd 16ths, in steps
    micro_ms: float  # σ of micro-timing on weak positions
    phrase_bars: tuple[int, ...]
    lead_db: float
    foundation_db: float
    support_db: float
    bed_db: float
    duck_lead_db: float
    duck_foundation_db: float
    foundation_keep: float  # share of the foundation motif's notes played
    ghosts: bool
    fills: bool
    conversation: bool
    bed_gaps: bool
    max_tonal_notes: int
    ghost_db: float = -10.0


SPECS = {
    "organic": ModeSpec(
        "organic",
        0.10,
        0.30,
        0.0,
        10.0,
        (3, 4, 5),
        -5.0,
        -8.0,
        -9.0,
        -14.0,
        5.0,
        2.0,
        0.55,
        False,
        False,
        False,
        False,
        3,
    ),
    "composed": ModeSpec(
        "composed",
        0.35,
        0.50,
        0.22,
        5.0,
        (4,),
        -4.0,
        -7.0,
        -8.0,
        -16.0,
        6.0,
        3.0,
        1.0,
        True,
        True,
        True,
        True,
        5,
    ),
}


# ----------------------------------------------------------------------------- data


@dataclass
class Note:
    step: float  # position in 16th steps from the start of the motif cell
    frag: Fragment
    vel: float  # 0…1
    ghost: bool = False
    dur_steps: float | None = None  # intended length (tonal notes / swells)
    midi_src: float | None = None  # measured pitch of the fragment
    shift_st: float = 0.0  # pitch move applied to the audio
    flags: tuple[str, ...] = ()


@dataclass
class Motif:
    id: str
    label: str
    kind: str  # rhythm | cycle | tonal | gesture | swell
    source: str
    cell_steps: int
    notes: list[Note]
    relation: dict[str, Any] | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "kind": self.kind,
            "source": self.source,
            "cell_steps": self.cell_steps,
            "relation": self.relation,
            "notes": [
                {
                    "step": round(n.step, 3),
                    "fragment": n.frag.id,
                    "vel": round(n.vel, 3),
                    "ghost": n.ghost,
                    **(
                        {}
                        if n.midi_src is None
                        else {"midi_src": round(n.midi_src, 2), "shift_st": round(n.shift_st, 3)}
                    ),
                    **({"flags": list(n.flags)} if n.flags else {}),
                }
                for n in self.notes
            ],
        }


# ----------------------------------------------------------------------------- motif builders


def _metric_weight(step: float) -> float:
    r = int(round(step)) % 16
    if r in ACCENT:
        return ACCENT[r]
    return 0.62 if r % 2 == 0 else 0.5


def build_rhythm_motif(
    label: str,
    key: str,
    m: Material,
    a: SourceAnalysis,
    step_s: float,
    q: float,
    swing: float,
    rng: np.random.Generator,
    cell_steps: int = 16,
    max_notes: int = 8,
) -> Motif | None:
    """A rhythmic cell from the source's *real* onset sequence (relative timing kept, then groove-mixed)."""
    attacks = {f.props["onset_s"]: f for f in m.attacks}
    if not attacks:
        return None
    onsets = sorted(t.meta["onset_s"] for t in a.transients)
    if len(onsets) < 2:
        f = m.attacks[0]
        return Motif(
            f"{key[:8]}:{label}",
            label,
            "rhythm",
            key,
            cell_steps,
            [Note(0.0, f, 0.6 + 0.4 * f.score)],
        )
    ioi = float(np.median(np.diff(onsets)))
    k = float(
        np.clip(round(ioi / step_s), 2, 6)
    )  # steps per median IOI: keeps the source's own pulse
    scale = (k * step_s) / ioi / step_s  # steps per second
    # pick the window of consecutive onsets with the best mean attack quality that fits the cell
    best: tuple[float, int, int] | None = None
    for i in range(len(onsets)):
        for c in range(3, max_notes + 1):
            j = i + c
            if j > len(onsets):
                break
            span = (onsets[j - 1] - onsets[i]) * scale
            if span > cell_steps - 1:
                break
            sc = float(
                np.mean(
                    [attacks[min(attacks, key=lambda t: abs(t - o))].score for o in onsets[i:j]]
                )
            )
            sc += 0.02 * c  # prefer a few more notes at equal quality
            if best is None or sc > best[0]:
                best = (sc, i, j)
    if best is None:
        i, j = 0, min(len(onsets), 3)
    else:
        _, i, j = best
    t0 = onsets[i]
    notes: list[Note] = []
    for o in onsets[i:j]:
        f = attacks[min(attacks, key=lambda t: abs(t - o))]
        raw = (o - t0) * scale
        quant = float(round(raw))
        pos = (1.0 - q) * raw + q * quant
        if swing > 0 and int(round(pos)) % 2 == 1:
            pos += swing
        w = _metric_weight(pos)
        vel = float(np.clip((0.45 + 0.55 * f.score) * (0.55 + 0.45 * w), 0.25, 1.0))
        notes.append(Note(float(pos), f, vel, ghost=False, flags=()))
    # ghost notes = the quietest 1–2 weak-position hits become ghosts (softer + shorter)
    weak = sorted((n for n in notes if _metric_weight(n.step) < 0.7), key=lambda n: n.vel)
    for n in weak[: max(0, min(2, len(notes) // 4))]:
        n.ghost = True
    return Motif(f"{key[:8]}:{label}", label, "rhythm", key, cell_steps, notes)


def build_cycle_motif(
    label: str, key: str, m: Material, a: SourceAnalysis, beat_steps: int, cell_steps: int = 16
) -> Motif | None:
    c = m.cycle
    if c is None:
        return None
    notes = [
        Note(float(s), c, 0.7 if s % 8 == 0 else 0.55, flags=("cycle",))
        for s in range(0, cell_steps, beat_steps)
    ]
    return Motif(f"{key[:8]}:{label}", label, "cycle", key, cell_steps, notes)


def build_tonal_motif(
    label: str,
    key: str,
    m: Material,
    step_s: float,
    rng: np.random.Generator,
    spec: ModeSpec,
    strategy: str = "contour",
) -> Motif | None:
    """A short monophonic motif from *reliable* pitched fragments. Returns None if the source is not pitched.

    strategy "contour" (default): keep the measured pitch relationships, fold suspected octave errors
    into the source's tonal centre, move the whole motif by octaves into 200–800 Hz, and only
    nudge a note to the nearest semitone when it is within 35 cents. strategy "pentatonic": snap every
    note to a minor-pentatonic scale on the tonal centre (the M4/M4.5 behaviour, kept for comparison).
    """
    if not m.tonal_reliable or m.tonal_center_midi is None:
        return None
    center = m.tonal_center_midi
    picked = sorted(m.tonal[: spec.max_tonal_notes], key=lambda f: f.start_s)
    if len(picked) < 2:
        return None
    # the register follows where the motif is *heard* (virtual pitches such as two-tone horns sound near their partials)
    octave_shift = register_octaves(
        m.register_center_midi if m.register_center_midi is not None else center
    )
    notes: list[Note] = []
    pos = 0.0
    for f in picked:
        measured = f.props["midi"]
        used = measured
        flags: list[str] = []
        k = round((measured - center) / 12.0)
        if k != 0 and abs(measured - center - 12 * k) < 0.8 and f.props["confidence"] < 0.92:
            used = measured - 12 * k  # likely an octave error relative to the source's own centre
            flags.append("octave_folded")
        target = used + 12 * octave_shift
        if strategy == "pentatonic":
            tones = [
                center + 12 * octave_shift + 12 * o + d
                for o in range(-2, 3)
                for d in (0, 3, 5, 7, 10)
            ]
            target = min(tones, key=lambda t: (abs(t - target), t))
            flags.append("pentatonic")
        else:
            cents = target - round(target)
            if abs(cents) <= 0.35:
                target = float(round(target))
                flags.append("tuned")
        target = float(np.clip(target, REGISTER_LOW - 6, REGISTER_HIGH + 6))
        dur_steps = float(np.clip(round(f.dur_s / step_s), 2, 8))
        shift = target - measured
        notes.append(
            Note(
                pos,
                f,
                float(np.clip(0.6 + 0.4 * f.score, 0.4, 1.0)),
                dur_steps=dur_steps,
                midi_src=measured,
                shift_st=float(shift),
                flags=tuple(flags),
            )
        )
        rest = (
            float(rng.choice([0, 2, 2, 4]))
            if spec.name == "composed"
            else float(rng.choice([2, 4, 4]))
        )
        pos += dur_steps + rest
    return Motif(
        f"{key[:8]}:{label}", label, "tonal", key, int(max(16, math.ceil(pos / 16) * 16)), notes
    )


def build_gesture_motif(label: str, key: str, m: Material) -> Motif | None:
    f = m.gesture or (m.attacks[0] if m.attacks else None)
    if f is None:
        return None
    return Motif(f"{key[:8]}:{label}", label, "gesture", key, 16, [Note(0.0, f, 0.9)])


def build_swell_motif(label: str, key: str, m: Material) -> Motif | None:
    f = m.texture or m.bed
    if f is None:
        return None
    return Motif(f"{key[:8]}:{label}", label, "swell", key, 32, [Note(0.0, f, 0.7, dur_steps=24.0)])


# ----------------------------------------------------------------------------- variations
# Each returns a NEW motif with `relation = {parent, operator, ...}`; the relation is the contract:
#   shift      – same fragments and order, every position moved by `steps` (mod cell): syncopation
#   density    – subset (drop weakest) or superset (+ghost notes in the gaps) of the parent's notes
#   fragment   – same positions, alternate hits use another real fragment of the same source
#   register   – tonal: all notes ± octaves, same order and intervals
#   retrograde – tonal: same notes, pitches reversed over the same positions
#   answer     – the first half of the parent only (a "question" shape)


def _clone(m: Motif, label: str, notes: list[Note], relation: dict[str, Any]) -> Motif:
    return Motif(
        f"{m.id.split(':')[0]}:{label}",
        label,
        m.kind,
        m.source,
        m.cell_steps,
        notes,
        {"parent": m.id, **relation},
    )


def v_shift(m: Motif, label: str, steps: float) -> Motif:
    ns = [replace(n, step=(n.step + steps) % m.cell_steps) for n in m.notes]
    ns.sort(key=lambda n: n.step)
    return _clone(m, label, ns, {"operator": "shift", "steps": steps})


def v_density(m: Motif, label: str, keep: float, ghosts: list[Fragment] | None = None) -> Motif:
    ns = sorted(m.notes, key=lambda n: -n.vel)
    kept = sorted(ns[: max(1, int(round(len(ns) * keep)))], key=lambda n: n.step)
    added = 0
    if ghosts:
        taken = {int(round(n.step)) for n in kept}
        for g in ghosts:
            slot = next(
                (s for s in (3, 7, 11, 15, 5, 13, 1, 9) if s not in taken and (s - 1) not in taken),
                None,
            )
            if slot is None:
                break
            kept.append(Note(float(slot), g, 0.35, ghost=True, flags=("ghost_added",)))
            taken.add(slot)
            added += 1
        kept.sort(key=lambda n: n.step)
    return _clone(m, label, kept, {"operator": "density", "keep": keep, "ghosts_added": added})


def v_fragment(m: Motif, label: str, alternates: list[Fragment]) -> Motif:
    if not alternates:
        return _clone(
            m, label, [replace(n) for n in m.notes], {"operator": "fragment", "swapped": 0}
        )
    ns, swapped = [], 0
    for i, n in enumerate(m.notes):
        if i % 2 == 1:
            alt = alternates[i // 2 % len(alternates)]
            if alt.id != n.frag.id:
                ns.append(replace(n, frag=alt, flags=n.flags + ("fragment_swapped",)))
                swapped += 1
                continue
        ns.append(replace(n))
    return _clone(m, label, ns, {"operator": "fragment", "swapped": swapped})


def v_register(m: Motif, label: str, octaves: int) -> Motif:
    ns = [
        replace(n, shift_st=n.shift_st + 12 * octaves, flags=n.flags + (f"octave{octaves:+d}",))
        for n in m.notes
    ]
    return _clone(m, label, ns, {"operator": "register", "octaves": octaves})


def v_retrograde(m: Motif, label: str) -> Motif:
    pitches = [(n.frag, n.midi_src, n.shift_st, n.flags) for n in m.notes][::-1]
    ns = [
        replace(n, frag=p[0], midi_src=p[1], shift_st=p[2], flags=p[3] + ("retrograde",))
        for n, p in zip(m.notes, pitches, strict=True)
    ]
    return _clone(m, label, ns, {"operator": "retrograde"})


def v_answer(m: Motif, label: str) -> Motif:
    half = max(1, math.ceil(len(m.notes) / 2))
    return _clone(
        m, label, [replace(n) for n in m.notes[:half]], {"operator": "answer", "notes": half}
    )


# ----------------------------------------------------------------------------- conversation


def motif_span(m: Motif, step_s: float) -> tuple[float, float]:
    """(first step, last step + audible length in steps)."""
    first = min(n.step for n in m.notes)
    last = max(
        n.step + (n.dur_steps if n.dur_steps else min(n.frag.dur_s / step_s, 4.0)) for n in m.notes
    )
    return first, last


def compatibility(
    lead: Motif,
    resp: Motif,
    ma: Material,
    mb: Material,
    a_a: SourceAnalysis,
    a_b: SourceAnalysis,
    step_s: float,
) -> dict[str, Any]:
    """Evidence that `resp` can answer `lead`: rests, spectral contrast, tonal consonance, pulse relation."""
    occ = {int(round(n.step)) for n in lead.notes}
    for n in lead.notes:
        occ.update(range(int(round(n.step)), int(round(n.step + (n.dur_steps or 2)))))
    free = [s for s in range(lead.cell_steps) if s not in occ and (s - 1) not in occ]
    rest_share = len(free) / lead.cell_steps
    rs = sorted(round(n.step) - round(resp.notes[0].step) for n in resp.notes)
    # place the answer after the lead's last note: how many of its notes still fit in the cell?
    _, end = motif_span(lead, step_s)
    start = int(math.ceil(end)) + 1
    fits = [s for s in rs if start + s < lead.cell_steps * 2]
    temporal = len(fits) / max(1, len(rs))
    ca = (
        np.mean([f.props["centroid_hz"] for f in ma.attacks])
        if ma.attacks
        else a_a.centroid_median_hz
    )
    cb = (
        np.mean([f.props["centroid_hz"] for f in mb.attacks])
        if mb.attacks
        else a_b.centroid_median_hz
    )
    spectral = float(np.clip(abs(math.log2(max(ca, 80) / max(cb, 80))) / 1.5, 0.0, 1.0))
    if ma.tonal_center_midi is not None and mb.tonal_center_midi is not None:
        interval = int(round(abs(ma.tonal_center_midi - mb.tonal_center_midi))) % 12
        tonal = 1.0 if interval in (0, 3, 4, 5, 7, 8, 9) else 0.3
    else:
        tonal = 0.6
    pulse = 0.5
    if a_a.period_s and a_b.period_s:
        r = a_a.period_s / a_b.period_s
        pulse = 1.0 if min(abs(r - x) for x in (0.5, 1.0, 1.5, 2.0)) < 0.08 else 0.35
    score = 0.4 * temporal + 0.25 * spectral + 0.2 * tonal + 0.15 * pulse
    return {
        "score": round(float(score), 3),
        "temporal_fit": round(temporal, 3),
        "lead_rest_share": round(rest_share, 3),
        "spectral_contrast": round(spectral, 3),
        "tonal_consonance": round(float(tonal), 3),
        "pulse_relation": round(pulse, 3),
    }


# ----------------------------------------------------------------------------- realisation


def _to_event(
    n: Note,
    motif: Motif,
    t: float,
    role_meta: dict[str, Any],
    step_s: float,
    gain_db: float,
    section: str,
    phrase_id: str,
    variation: str | None,
    lowpass: float | None,
    lane: tuple[float | None, float | None] | None = None,
) -> dict[str, Any]:
    f = n.frag
    gain = gain_db + 20 * math.log10(max(n.vel, 1e-3)) + (-10.0 if n.ghost else 0.0)
    ev: dict[str, Any] = {
        "kind": "slice",
        "t": t,
        "section": section,
        "source_start_s": f.start_s,
        "source_end_s": f.end_s,
        "gain_db": round(gain, 2),
        "rate": 1.0,
        "lowpass_hz": lowpass or 12000.0,
        "fade_in_s": 0.004,
        "fade_out_s": 0.05,
        "velocity": round(n.vel, 3),
        "ghost": n.ghost,
        "motif": motif.id,
        "variation": variation,
        "phrase": phrase_id,
        "hierarchy": role_meta["hierarchy"],
        "fragment": f.id,
        "dur": min(f.dur_s, 0.35) * (0.6 if n.ghost else 1.0),
        "fg_window_s": 0.1,  # how long the attack holds the foreground (tonal notes override below)
    }
    if motif.kind == "tonal":
        dur = float(n.dur_steps or 4) * step_s
        take = min(f.dur_s, dur)
        ev["source_end_s"] = f.start_s + take
        ev["dur"] = dur * 1.05
        ev["pitch_shift_st"] = round(n.shift_st, 3)
        ev["rate"] = round(2.0 ** (n.shift_st / 12.0), 5)
        ev["preserve_duration"] = abs(n.shift_st) >= 1.0
        ev["fade_in_s"] = 0.012
        ev["fade_out_s"] = min(0.12, dur * 0.4)
        ev["fg_window_s"] = min(0.35, dur)
        ev["tonal_flags"] = list(n.flags)
    elif motif.kind == "cycle":
        per = f.props.get("period_s", f.dur_s)
        ev["rate"] = round(float(np.clip(per / (4 * step_s), 0.7, 1.4)), 4)
        ev["dur"] = f.dur_s / ev["rate"]
        ev["fade_in_s"], ev["fade_out_s"] = 0.02, 0.05
    elif motif.kind == "swell":
        dur = float(n.dur_steps or 16) * step_s
        ev.update(
            {
                "kind": "loop",
                "dur": dur,
                "fade_in_s": dur * 0.4,
                "fade_out_s": dur * 0.4,
                "crossfade_s": 0.5,
            }
        )
    elif motif.kind == "gesture":
        ev["rate"] = 0.85
        ev["fade_out_s"] = 0.12
        ev["dur"] = f.dur_s * 1.4
    if lane:
        if lane[0]:
            ev["highpass_hz"] = lane[0]
        if lane[1]:
            ev["lowpass_hz"] = min(ev["lowpass_hz"], lane[1])
    return ev


def enforce_foreground(
    events: list[dict[str, Any]], limit: int = FOREGROUND_LIMIT, window_s: float = 0.25
) -> int:
    """Drop lowest-priority foreground events so that at most `limit` attack windows overlap. Returns #dropped."""
    fg = sorted(
        (e for e in events if e["hierarchy"] in FOREGROUND),
        key=lambda e: (e["t"], PRIORITY[e["hierarchy"]]),
    )
    keep: list[dict[str, Any]] = []
    dropped = 0
    drop_ids: set[int] = set()
    for e in fg:
        s, en = e["t"], e["t"] + min(e["dur"], e.get("fg_window_s", window_s))
        active = [
            k for k in keep if k["t"] + min(k["dur"], k.get("fg_window_s", window_s)) > s + 1e-9
        ]
        if len(active) >= limit:
            worst = max(
                [*active, e], key=lambda x: (PRIORITY[x["hierarchy"]], -x["velocity"], -x["t"])
            )
            if worst is e:
                drop_ids.add(id(e))
                dropped += 1
                continue
            keep.remove(worst)
            drop_ids.add(id(worst))
            dropped += 1
        keep.append(e)
        del en
    events[:] = [e for e in events if id(e) not in drop_ids]
    return dropped


# ----------------------------------------------------------------------------- composition


def _phrase_lengths(total: int, spec: ModeSpec, rng: np.random.Generator) -> list[int]:
    out: list[int] = []
    left = total
    while left > 0:
        n = int(rng.choice(spec.phrase_bars)) if len(spec.phrase_bars) > 1 else spec.phrase_bars[0]
        n = min(n, left)
        if left - n == 1:  # never leave a one-bar orphan
            n = left
        out.append(n)
        left -= n
    return out


def _section_bars(total: int, n_active: int) -> list[int]:
    w = np.array([0.18, 0.27, 0.35, 0.20])
    bars = np.maximum(2, np.round(w * total).astype(int))
    while bars.sum() > total:
        bars[int(np.argmax(bars))] -= 1
    while bars.sum() < total:
        bars[2] += 1
    del n_active
    return [int(b) for b in bars]


def compose_plan(
    analyses: list[SourceAnalysis],
    roles: dict[str, RoleDecision],
    materials: dict[str, Material],
    *,
    seed: int,
    mode: str = "composed",
    controls: dict[str, float] | None = None,
    duration_s: float = 45.0,
    tonal_strategy: str = "contour",
    groove_q: float | None = None,
) -> dict[str, Any]:
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}")
    spec = SPECS[mode]
    c = {"density": 0.5, "structure": 0.5, "intensity": 0.5}
    c.update(controls or {})
    c = {k: float(min(1.0, max(0.0, v))) for k, v in c.items()}
    if not analyses:
        raise ValueError("at least one source is required")
    if len(analyses) > MAX_SOURCES:
        raise ValueError(f"at most {MAX_SOURCES} sources")
    duration_s = float(min(90.0, max(15.0, duration_s)))
    analyses = sorted(analyses, key=lambda a: a.key)
    by_key = {a.key: a for a in analyses}

    base_bpm, tempo_src = choose_tempo(analyses, roles)
    bpm = round(base_bpm * (0.92 + 0.16 * c["intensity"]), 2)
    beat_s = 60.0 / bpm
    bar_s = 4 * beat_s
    step_s = bar_s / STEPS_PER_BAR
    total_bars = max(8, int(round(duration_s / bar_s)))
    q = float(np.clip(spec.quant_base + spec.quant_span * c["structure"], 0.0, 1.0))
    if groove_q is not None:  # experiments only: 0 = source-timed, 1 = fully quantised
        q = float(np.clip(groove_q, 0.0, 1.0))
    keep_density = 0.45 + 0.55 * c["density"]

    # ---- layer selection ---------------------------------------------------------------
    def rhythm_quality(k: str) -> float:
        m = materials[k]
        top = [f.score for f in m.attacks[:4]]
        return (
            float(np.mean(top))
            if len(top) >= 3
            else (0.0 if m.cycle is None else 0.35 * m.cycle.score)
        )

    # Beds first: steady material (stability >= 0.45) whose measured role is atmospheric or a steady pulse
    # (an engine is a fine drone). A source is a bed OR a foreground voice, never both.
    bed_pool = sorted(
        (
            k
            for k in by_key
            if materials[k].bed is not None
            and by_key[k].stability >= 0.45
            and not materials[k].tonal_reliable
            and roles[k].primary in (*ATMOSPHERE_ROLES, "rhythmic_texture")
        ),
        key=lambda k: (-by_key[k].stability, k),
    )[:2]
    in_bed = set(bed_pool)
    all_rhythm = sorted(
        (k for k in by_key if rhythm_quality(k) > 0), key=lambda k: (-rhythm_quality(k), k)
    )
    rhythm_pool = [k for k in all_rhythm if k not in in_bed] or all_rhythm
    tonal_pool = sorted(
        (k for k in by_key if materials[k].tonal_reliable),
        key=lambda k: (-float(np.mean([f.score for f in materials[k].tonal])), k),
    )

    lead_src = lead_kind = None
    if tonal_pool:
        lead_src, lead_kind = tonal_pool[0], "tonal"
    elif rhythm_pool:
        lead_src, lead_kind = rhythm_pool[0], "rhythm"
    else:
        lead_src = next((k for k in by_key if materials[k].texture or materials[k].bed), None)
        lead_kind = "swell"
    if lead_src is None:
        raise ValueError("the selected recordings contain no usable musical material")
    found_src = next((k for k in rhythm_pool if k != lead_src), None)
    if found_src is None and lead_kind == "tonal" and rhythm_pool:
        found_src = rhythm_pool[0]
    support_srcs = [k for k in rhythm_pool if k not in (lead_src, found_src)]
    support_src = support_srcs[0] if support_srcs else None
    beds = [k for k in bed_pool if k not in (lead_src, found_src, *support_srcs)]
    if not beds and lead_kind == "swell" and materials[lead_src].bed:
        beds = [lead_src]

    # gestures mark section boundaries; they come from sources that are not already lead/foundation/answer/bed
    tonal_voices = [k for k in tonal_pool if k != lead_src][
        :2
    ]  # further pitched sources answer melodically
    used_voices = {lead_src, found_src, *support_srcs, *beds, *tonal_voices}
    gesture_srcs = [
        k
        for k in sorted(by_key)
        if k not in used_voices and (materials[k].gesture or materials[k].attacks)
    ]
    gesture_src = gesture_srcs[0] if gesture_srcs else None
    # ---- motifs -----------------------------------------------------------------------
    motifs: dict[str, Motif] = {}

    def add(label: str, mo: Motif | None) -> Motif | None:
        if mo is not None:
            motifs[label] = mo
        return mo

    rng_m = rng_for(seed, "motifs")
    A: Motif | None = None
    if lead_kind == "tonal":
        A = add(
            "A",
            build_tonal_motif(
                "A", lead_src, materials[lead_src], step_s, rng_m, spec, tonal_strategy
            ),
        )
    elif lead_kind == "rhythm":
        A = add(
            "A",
            build_rhythm_motif(
                "A", lead_src, materials[lead_src], by_key[lead_src], step_s, q, spec.swing, rng_m
            ),
        )
    if A is None and lead_src is not None:
        A = add("A", build_swell_motif("A", lead_src, materials[lead_src]))
        lead_kind = "swell"

    F: Motif | None = None
    if found_src is not None:
        F = build_rhythm_motif(
            "F", found_src, materials[found_src], by_key[found_src], step_s, q, spec.swing, rng_m
        )
        if F is None or len(F.notes) < 2:
            F = build_cycle_motif("F", found_src, materials[found_src], by_key[found_src], 4) or F
        if F is not None and spec.foundation_keep < 1.0:
            F = v_density(F, "F", spec.foundation_keep)
            F.label = "F"
        if F is not None:
            motifs["F"] = F
    Rs: list[Motif] = []
    for ri, sk in enumerate(support_srcs[:3]):
        r = build_rhythm_motif(
            "R" if ri == 0 else f"R{ri + 1}",
            sk,
            materials[sk],
            by_key[sk],
            step_s,
            q,
            spec.swing,
            rng_m,
            max_notes=5,
        )
        if r is not None:
            Rs.append(r)
            motifs[r.label] = r
    for ti, tk in enumerate(tonal_voices):
        tm = build_tonal_motif(
            f"T{ti + 1}",
            tk,
            materials[tk],
            step_s,
            rng_for(seed, f"tonal-voice-{ti}"),
            spec,
            tonal_strategy,
        )
        if tm is not None:
            Rs.append(tm)
            motifs[tm.label] = tm
    Gs: list[Motif] = []
    for gi, gk in enumerate(gesture_srcs[:3]):
        g = build_gesture_motif("G" if gi == 0 else f"G{gi + 1}", gk, materials[gk])
        if g is not None:
            Gs.append(g)
            motifs[g.label] = g

    # variations (documented relations; every variant has a single operator on a registered parent)
    var: dict[str, Motif] = {}

    def octave_ok(mo: Motif, octaves: int) -> bool:
        tgt = [n.midi_src + n.shift_st + 12 * octaves for n in mo.notes if n.midi_src is not None]
        return bool(tgt) and REGISTER_LOW - 6 <= min(tgt) and max(tgt) <= REGISTER_HIGH + 6

    if A is not None:
        var["A"] = A
        if A.kind == "tonal":
            var["A'"] = v_density(A, "A'", 0.75) if len(A.notes) > 3 else v_answer(A, "A'")
            var["A''"] = v_retrograde(A, "A''")
            var["A'''"] = v_answer(A, "A'''")
            var["B"] = v_register(A, "B", 1 if octave_ok(A, 1) else (-1 if octave_ok(A, -1) else 0))
        else:
            alts = [
                f for f in materials[A.source].attacks if f.id not in {n.frag.id for n in A.notes}
            ]
            var["A'"] = v_shift(A, "A'", 2.0 if spec.name == "composed" else 1.0)
            var["A''"] = v_fragment(A, "A''", alts)
            var["A'''"] = v_density(A, "A'''", 0.6)
            var["B"] = (
                v_density(A, "B", 1.0, alts[:2]) if spec.ghosts and alts else v_shift(A, "B", 3.0)
            )
    if F is not None:
        var["F"] = F
        alts = [f for f in materials[F.source].attacks if f.id not in {n.frag.id for n in F.notes}]
        var["F'"] = (
            v_density(F, "F'", 1.0, alts[:2]) if spec.ghosts and alts else v_shift(F, "F'", 1.0)
        )
        var["F''"] = v_density(F, "F''", 0.5)
        var["Fa"] = v_fragment(F, "Fa", alts)

    # conversation partners for the lead: scored on temporal fit, spectral contrast, tonal and pulse relation
    conversation: list[dict[str, Any]] = []
    responders: list[Motif] = []
    if A is not None:
        cands = [
            m
            for m in (*Rs, F)
            if m is not None
            and m.source != A.source
            and m.kind in ("rhythm", "cycle", "gesture", "tonal")
        ]
        scored = []
        for cand in cands:
            ev = compatibility(
                A,
                cand,
                materials[A.source],
                materials[cand.source],
                by_key[A.source],
                by_key[cand.source],
                step_s,
            )
            scored.append((ev["score"], cand.id, cand, ev))
        scored.sort(key=lambda t: (-t[0], t[1]))
        for sc, _, cand, ev in scored[:3]:
            if sc >= 0.45:
                responders.append(cand)
                conversation.append(
                    {
                        "lead": A.id,
                        "responder": cand.id,
                        "lead_source": A.source,
                        "responder_source": cand.source,
                        "evidence": ev,
                    }
                )
    responder: Motif | None = responders[0] if responders else None
    resp_turn = 0

    # ---- sections, phrases, events ------------------------------------------------------
    sec_bars = _section_bars(total_bars, len(analyses))
    sections: list[dict[str, Any]] = []
    cur = 0
    for name, nb in zip(SECTIONS, sec_bars, strict=True):
        sections.append(
            {
                "name": name,
                "start_bar": cur,
                "bars": nb,
                "start_s": round(cur * bar_s, 4),
                "end_s": round((cur + nb) * bar_s, 4),
            }
        )
        cur += nb
    total_s = total_bars * bar_s

    tracks: list[dict[str, Any]] = []
    tid_of: dict[tuple[str, str], str] = {}

    def track(
        src: str,
        hierarchy: str,
        base_db: float,
        pan: float,
        reverb: float,
        lane: tuple[float | None, float | None] | None = None,
    ) -> str:
        kk = (src, hierarchy)
        if kk not in tid_of:
            tid = f"t{len(tracks) + 1}"
            tid_of[kk] = tid
            tracks.append(
                {
                    "id": tid,
                    "source": src,
                    "role": "tonal_motif"
                    if hierarchy == "support" and src in tonal_voices
                    else _legacy_role(
                        hierarchy, roles[src].primary, lead_kind if hierarchy == "lead" else None
                    ),
                    "hierarchy": hierarchy,
                    "layer_order": len(tracks),
                    "pan": round(pan, 3),
                    "reverb_send": reverb,
                    "base_gain_db": base_db,
                    "enters": "introduction",
                    "lane": lane,
                }
            )
        return tid_of[kk]

    events: list[dict[str, Any]] = []
    phrases: list[dict[str, Any]] = []
    form: dict[str, str] = {}
    micro_rng = rng_for(seed, "microtiming")
    layout_rng = rng_for(seed, "layout")

    comp_sec_db = (
        {"introduction": -5.0, "discovery": -2.5, "convergence": 1.0, "resolution": -5.0}
        if mode == "composed"
        else {"introduction": -6.5, "discovery": -3.0, "convergence": 3.5, "resolution": -6.5}
    )

    def ramp_scale(sec_name: str, pi: int, n_phr: int) -> float:
        """Velocity scale across the phrases of a section: crescendo into/through the convergence,
        decrescendo in the resolution (a gain shape, not a loudness boost)."""
        u = pi / max(1, n_phr - 1)
        lo, hi = {
            "introduction": (0.9, 1.0),
            "discovery": (0.82, 0.95),
            "convergence": (0.85, 1.0),
            "resolution": (0.95, 0.6),
        }[sec_name]
        return lo + (hi - lo) * u

    intens_db = (c["intensity"] - 0.5) * 5.0

    def level(src: str, hier: str, sec: str) -> float:
        comp = float(np.clip(0.6 * (TARGET_RMS_DB - by_key[src].rms_dbfs), -12.0, 12.0))
        base = {
            "lead": spec.lead_db,
            "foundation": spec.foundation_db,
            "support": spec.support_db,
            "gesture": -3.0,
            "bed": spec.bed_db,
        }[hier]
        # beds follow their own section boosts (set where they are placed), so they can recede when the
        # foreground enters instead of rising with it
        sec_term = 0.0 if hier == "bed" else comp_sec_db[sec]
        return base + comp + sec_term + (intens_db if sec == "convergence" else 0.4 * intens_db)

    # ---- fragment ledger: how often each real fragment has sounded in this piece -------------------
    usage: dict[str, int] = {}
    recent: dict[str, list[str]] = {}
    reuse_cap = max(8, int(round(total_bars * 0.5)))  # per fragment, per piece

    def use_fragment(src: str, f: Fragment) -> None:
        usage[f.id] = usage.get(f.id, 0) + 1
        recent.setdefault(src, []).append(f.id)

    def pick_attack(src: str, default: Fragment, weak: bool) -> Fragment | None:
        pool = materials[src].attacks
        if len(pool) < 3:
            return default
        best = pool[0].score
        cands = [f for f in pool if f.score >= max(0.25, 0.6 * best)][: (7 if weak else 4)]
        last = recent.get(src, [])[-5:]
        cands.sort(
            key=lambda f: (
                usage.get(f.id, 0) + (3.0 if f.id in last else 0.0) - 2.0 * f.score,
                f.id,
            )
        )
        pick = cands[0]
        if usage.get(pick.id, 0) >= reuse_cap:
            # widen to every real attack of this source (not only the best-scored), least used first
            wide = sorted(pool, key=lambda f: (usage.get(f.id, 0), -f.score, f.id))
            pick = wide[0]
            if usage.get(pick.id, 0) >= reuse_cap and weak:
                return None  # silence is better than wearing out one sample
        return pick

    def place(
        mo: Motif,
        hier: str,
        sec: dict[str, Any],
        phrase_id: str,
        bar0: int,
        bars_avail: int,
        variation: str | None,
        step_offset: float = 0.0,
        skip_steps: set[int] | None = None,
        vel_scale: float = 1.0,
    ) -> list[dict[str, Any]]:
        tid = track(
            mo.source,
            hier,
            spec.lead_db,
            0.0 if hier == "lead" else (-0.3 if hier == "foundation" else 0.35),
            0.18 if hier == "lead" else 0.1,
        )
        out = []
        cell = mo.cell_steps
        repeats = max(1, int(math.ceil(bars_avail * 16 / cell)))
        for r in range(repeats if hier == "foundation" and variation != "response" else 1):
            for n in mo.notes:
                pos = n.step + step_offset + r * cell
                if pos >= bars_avail * 16:
                    continue
                if skip_steps and int(round(pos)) in skip_steps:
                    continue
                t = (sec["start_bar"] + bar0) * bar_s + pos * step_s
                if not (n.ghost or _metric_weight(pos) >= 0.9):
                    t += float(
                        np.clip(micro_rng.normal(0.0, spec.micro_ms / 1000.0), -0.014, 0.014)
                    )
                frag = n.frag
                weak = n.ghost or _metric_weight(pos) < 0.9
                if hier == "foundation" and mo.kind == "rhythm":
                    # diversify: choose among the source's good attacks, penalising heavy and recent use;
                    # when every good candidate is worn out, weak/ghost positions rest instead
                    picked = pick_attack(mo.source, frag, weak)
                    if picked is None:
                        continue
                    frag = picked
                use_fragment(mo.source, frag)
                nn = replace(n, frag=frag, vel=float(np.clip(n.vel * vel_scale, 0.15, 1.0)))
                e = _to_event(
                    nn,
                    mo,
                    max(0.0, t),
                    {"hierarchy": hier},
                    step_s,
                    level(mo.source, hier, sec["name"]),
                    sec["name"],
                    phrase_id,
                    variation,
                    None,
                )
                e["track"], e["source"], e["role"] = (
                    tid,
                    mo.source,
                    tracks[int(tid[1:]) - 1]["role"],
                )
                out.append(e)
        return out

    def occupied(evs: list[dict[str, Any]], sec: dict[str, Any], bar0: int) -> set[int]:
        base = (sec["start_bar"] + bar0) * bar_s
        occ: set[int] = set()
        for e in evs:
            s0 = int(round((e["t"] - base) / step_s))
            s1 = int(round((e["t"] + min(e["dur"], 0.3) - base) / step_s))
            occ.update(range(s0 - 1, s1 + 2))
        return occ

    def fill_events(
        src: str, sec: dict[str, Any], bar_idx: int, phrase_id: str
    ) -> list[dict[str, Any]]:
        m = materials[src]
        if not m.attacks:
            return []
        out = []
        tid = track(src, "foundation", spec.foundation_db, -0.3, 0.1)
        base = (sec["start_bar"] + bar_idx) * bar_s
        for i, s in enumerate((12, 13, 14, 15)):
            f = pick_attack(src, m.attacks[(i + 1 + bar_idx) % len(m.attacks)], True)
            if f is None:
                continue
            use_fragment(src, f)
            nn = Note(float(s), f, 0.45 + 0.1 * i)
            e = _to_event(
                nn,
                Motif("fill", "fill", "rhythm", src, 16, [nn]),
                base + s * step_s,
                {"hierarchy": "foundation"},
                step_s,
                level(src, "foundation", sec["name"]),
                sec["name"],
                phrase_id,
                "fill",
                None,
            )
            e["track"], e["source"], e["role"] = tid, src, tracks[int(tid[1:]) - 1]["role"]
            out.append(e)
        return out

    layout = _layout(mode)
    sec_lens: dict[str, list[int]] = {}
    for sec in sections:
        name = sec["name"]
        lens = _phrase_lengths(sec["bars"], spec, layout_rng)
        sec_lens[name] = lens
        recipes = layout[name]
        labels: list[str] = []
        b = 0
        for pi, plen in enumerate(lens):
            recipe = recipes[pi % len(recipes)]
            pid = f"{name[:3]}{pi + 1}"
            ph_events: list[dict[str, Any]] = []
            used = []
            lead_events: list[dict[str, Any]] = []
            if A is not None and recipe.get("lead") in var:
                if A.kind in ("tonal", "swell"):
                    lv = var[recipe["lead"]]
                    # organic: the bed establishes itself for a bar before the lead enters
                    delay = 1 if (mode == "organic" and name == "introduction" and plen >= 3) else 0
                    lead_events = place(
                        lv,
                        "lead",
                        sec,
                        pid,
                        b + delay,
                        plen - delay,
                        lv.label if lv.label != "A" else None,
                        vel_scale=ramp_scale(name, pi, len(lens)),
                    )
                    used.append(recipe["lead"])
                else:  # rhythmic lead: one variant per bar (A A' B ...), the last bar of the phrase rests
                    seq = recipe.get("bars") or [recipe["lead"]]
                    for bi in range(max(1, plen - 1)):
                        lv = var.get(seq[bi % len(seq)], A)
                        lead_events += place(
                            lv,
                            "lead",
                            sec,
                            pid,
                            b + bi,
                            1,
                            lv.label if lv.label != "A" else None,
                            vel_scale=ramp_scale(name, pi, len(lens)),
                        )
                    used.append(" ".join(dict.fromkeys(seq[: max(1, plen - 1)])))
                last_bar_start = (sec["start_bar"] + b + plen - 1) * bar_s
                lead_events = [
                    e for e in lead_events if e["t"] < last_bar_start - 1e-9 or plen <= 2
                ]
                ph_events += lead_events
            if F is not None and recipe.get("foundation") in var and (name != "introduction"):
                fseq = recipe.get("fbars") or [recipe["foundation"]]
                skip = (
                    occupied(lead_events, sec, b)
                    if lead_kind == "rhythm" and found_src == lead_src
                    else None
                )
                fe: list[dict[str, Any]] = []
                for bi in range(
                    plen
                ):  # one variant per bar: the groove breathes instead of looping
                    fv = var.get(fseq[bi % len(fseq)], F)
                    fe += place(
                        fv,
                        "foundation",
                        sec,
                        pid,
                        b + bi,
                        1,
                        fv.label if fv.label != "F" else None,
                        skip_steps=None,
                        vel_scale=(keep_density if mode == "organic" else 1.0)
                        * ramp_scale(name, pi, len(lens)),
                    )
                if skip:
                    fe = [
                        e
                        for e in fe
                        if int(round((e["t"] - (sec["start_bar"] + b) * bar_s) / step_s))
                        not in skip
                    ]
                ph_events += fe
                used.append(" ".join(dict.fromkeys(fseq[:plen])))
                if (
                    spec.fills
                    and recipe.get("fill")
                    and plen >= 3
                    and name in ("discovery", "convergence")
                ):
                    ph_events += fill_events(F.source, sec, b + plen - 1, pid)
            if (
                responders
                and recipe.get("response")
                and lead_events
                and (spec.conversation or name == "convergence")
            ):
                occ = occupied(lead_events, sec, b)
                lead_end = max(
                    (
                        int(
                            round(
                                (e["t"] + min(e["dur"], 0.3) - (sec["start_bar"] + b) * bar_s)
                                / step_s
                            )
                        )
                        for e in lead_events
                    ),
                    default=0,
                )
                start = lead_end + 2
                responder = responders[resp_turn % len(responders)]
                resp_turn += 1
                rsp = place(
                    responder,
                    "foundation" if responder.source == found_src else "support",
                    sec,
                    pid,
                    b,
                    plen,
                    "response",
                    step_offset=float(start),
                    skip_steps=occ,
                    vel_scale=0.9 * ramp_scale(name, pi, len(lens)),
                )
                lead_id = A.id if A is not None else ""
                for e in rsp:
                    e["response_to"] = lead_id
                ph_events += rsp
                if rsp:  # make room: the groove thins around the answer so it can be heard
                    lo = min(e["t"] for e in rsp) - 1.5 * step_s
                    hi = max(e["t"] for e in rsp) + 1.5 * step_s
                    kept: list[dict[str, Any]] = []
                    for e in ph_events:
                        if (
                            e["hierarchy"] == "foundation"
                            and e.get("variation") != "response"
                            and lo <= e["t"] <= hi
                        ):
                            if any(abs(e["t"] - r["t"]) < 1.5 * step_s for r in rsp):
                                continue
                            e["gain_db"] = round(e["gain_db"] - 4.0, 2)
                        kept.append(e)
                    ph_events = kept
                used.append("R→" + lead_id.split(":")[-1])
            if Gs and b == 0 and name != "introduction":
                gev = place(
                    Gs[SECTIONS.index(name) % len(Gs)], "gesture", sec, pid, 0, plen, "boundary"
                )
                ph_events += gev
            events += ph_events
            phrases.append(
                {
                    "id": pid,
                    "section": name,
                    "start_bar": sec["start_bar"] + b,
                    "bars": plen,
                    "motifs": used,
                    "events": len(ph_events),
                }
            )
            labels.append(" + ".join(used) if used else "–")
            b += plen
        form[name] = " | ".join(labels)

    # ---- beds (atmosphere): quiet, band-limited, with air gaps ----------------------------
    bed_tracks: list[str] = []
    atmos_sorted = sorted(beds, key=lambda k: (by_key[k].centroid_median_hz, k))
    for rank, bk in enumerate(atmos_sorted):
        lane = (
            lane_band(
                rank,
                len(atmos_sorted),
                LANE_EDGES_HZ[: len(atmos_sorted) + 1] if len(atmos_sorted) <= 3 else LANE_EDGES_HZ,
            )
            if len(atmos_sorted) >= 2
            else (None, None)
        )
        tid = track(bk, "bed", spec.bed_db, (-0.5 if rank % 2 == 0 else 0.5) * 0.8, 0.14, lane)
        bed_tracks.append(tid)
        frag = materials[bk].bed
        assert frag is not None
        for sec in sections:
            name = sec["name"]
            if rank >= 1 and name in ("discovery",):
                continue  # the second bed only colours the introduction, convergence and resolution
            lens = sec_lens[name]
            b = 0
            chunks: list[tuple[int, int]] = []
            if spec.bed_gaps:
                for plen in lens:
                    chunks.append((b, max(1, plen - 1)))  # air in the phrase's last bar
                    b += plen
            else:
                chunks = [(0, sec["bars"])]
            for cb, cl in chunks:
                start = (sec["start_bar"] + cb) * bar_s
                dur = cl * bar_s
                fade = min(1.2, dur * 0.35)
                # absolute bed offsets per section (beds ignore the foreground section offsets): composed keeps its
                # M4.6 effective values; organic has a quiet introduction and a bed that recedes in the convergence
                boost = (
                    {
                        "introduction": -4.0,
                        "discovery": -3.5,
                        "convergence": -2.0,
                        "resolution": -5.0,
                    }[name]
                    if spec.name == "composed"
                    else {
                        "introduction": -5.5,
                        "discovery": -6.0,
                        "convergence": -8.5,
                        "resolution": -8.0,
                    }[name]
                )
                e = {
                    "kind": "loop",
                    "t": max(0.0, start - fade / 2),
                    "dur": dur + fade,
                    "section": name,
                    "source_start_s": frag.start_s,
                    "source_end_s": frag.end_s,
                    "rate": 1.0,
                    "crossfade_s": 0.9,
                    "fade_in_s": fade,
                    "fade_out_s": min(3.0, dur * 0.6)
                    if name == "resolution" and cb == chunks[-1][0]
                    else fade,
                    "gain_db": round(level(bk, "bed", name) + boost, 2),
                    "lowpass_hz": 4500.0 if name != "convergence" else 3000.0,
                    "hierarchy": "bed",
                    "motif": None,
                    "variation": None,
                    "phrase": None,
                    "velocity": 1.0,
                    "ghost": False,
                    "fragment": frag.id,
                }
                if lane[0]:
                    e["highpass_hz"] = lane[0]
                if lane[1]:
                    e["lowpass_hz"] = min(e["lowpass_hz"], lane[1])
                e["track"], e["source"], e["role"] = tid, bk, tracks[int(tid[1:]) - 1]["role"]
                events.append(e)

    dropped = enforce_foreground(events)
    # a layer that lost every event (or never had one) is removed so no empty stems are exported
    active = {e["track"] for e in events}
    tracks = [t for t in tracks if t["id"] in active]
    for i, t in enumerate(tracks):
        t["layer_order"] = i
        first = min(e["t"] for e in events if e["track"] == t["id"])
        t["enters"] = next(
            (s["name"] for s in sections if first < s["end_s"] - 1e-9), "convergence"
        )
    if len(events) > MAX_EVENTS:
        events = sorted(events, key=lambda e: (PRIORITY.get(e["hierarchy"], 9), e["t"]))[
            :MAX_EVENTS
        ]
    events.sort(key=lambda e: (e["t"], e["track"], e["kind"]))
    for i, e in enumerate(events):
        e["seq"] = i
        e["t"] = round(float(e["t"]), 5)
        e["dur"] = round(float(e["dur"]), 5)

    depth = {
        t["id"]: (
            spec.duck_lead_db
            if t["hierarchy"] == "lead"
            else spec.duck_foundation_db
            if t["hierarchy"] in ("foundation", "support")
            else 4.0
        )
        for t in tracks
        if t["hierarchy"] in ("lead", "foundation", "support", "gesture")
    }
    ducking = {
        "depth_db": spec.duck_lead_db,
        "depths": depth,
        "attack_s": 0.015,
        "release_s": 0.3,
        "max_hold_s": 0.4,
        "targets": [t["id"] for t in tracks if t["hierarchy"] == "bed"],
        "triggers": [
            t["id"]
            for t in tracks
            if t["hierarchy"] in ("lead", "foundation", "support", "gesture")
        ],
    }

    key_info = None
    if A is not None and A.kind == "tonal":
        key_info = {
            "tonic_midi": round(materials[A.source].tonal_center_midi or 0.0, 3),
            "scale": "none (measured contour)"
            if tonal_strategy == "contour"
            else "minor_pentatonic",
            "from": "confidence-weighted median of reliable pitched fragments",
            "register_octaves_moved": register_octaves(
                materials[A.source].tonal_center_midi or 60.0
            ),
        }
    return {
        "planner_version": COMPOSER_VERSION,
        "mode": mode,
        "seed": int(seed),
        "controls": c,
        "tempo_bpm": bpm,
        "tempo_source": tempo_src,
        "time_signature": "4/4",
        "key": key_info,
        "duration_s": round(total_s, 4),
        "tail_s": 2.5,
        "bar_s": round(bar_s, 5),
        "groove": {
            "quantisation": round(q, 3),
            "swing_steps": spec.swing,
            "micro_ms": spec.micro_ms,
            "ghost_notes": spec.ghosts,
            "fills": spec.fills,
            "tonal_strategy": tonal_strategy,
        },
        "sections": sections,
        "tracks": tracks,
        "ducking": ducking,
        "events": events,
        "sources": [a.key for a in analyses],
        "motifs": [
            mo.to_json() for mo in {**motifs, **{v.label: v for v in var.values()}}.values()
        ],
        "phrases": phrases,
        "form": form,
        "conversation": conversation,
        "hierarchy": {
            "lead": lead_src,
            "lead_kind": lead_kind,
            "foundation": found_src,
            "support": support_src,
            "beds": beds,
            "gesture": gesture_src,
        },
        "foreground_dropped": dropped,
    }


def _legacy_role(hierarchy: str, primary: str, lead_kind: str | None) -> str:
    """Map the hierarchy onto the M4 role vocabulary so persistence, UI chips and ducking stay valid."""
    if hierarchy == "lead":
        return (
            "tonal_motif"
            if lead_kind == "tonal"
            else ("texture" if lead_kind == "swell" else "percussion")
        )
    if hierarchy in ("foundation", "support"):
        return "rhythmic_texture" if primary == "rhythmic_texture" else "percussion"
    if hierarchy == "gesture":
        return "accent"
    return primary if primary in ATMOSPHERE_ROLES else "texture"


def _layout(mode: str) -> dict[str, list[dict[str, Any]]]:
    """Phrase recipes per section. `lead` = tonal/swell variant; `bars` = per-bar variants for rhythmic leads."""
    if mode == "composed":
        return {
            "introduction": [{"lead": "A", "bars": ["A"]}],
            "discovery": [
                {"lead": "A'", "bars": ["A", "A'"], "response": True},
                {
                    "lead": "A",
                    "bars": ["A", "A'", "A"],
                    "foundation": "F",
                    "fbars": ["F", "F'", "F", "Fa"],
                    "response": True,
                    "fill": True,
                },
            ],
            "convergence": [
                {
                    "lead": "A",
                    "bars": ["A", "A'", "B"],
                    "foundation": "F",
                    "fbars": ["F", "F'", "F", "Fa"],
                    "response": True,
                    "fill": True,
                },
                {
                    "lead": "A''",
                    "bars": ["A", "A''", "A'"],
                    "foundation": "F'",
                    "fbars": ["F'", "Fa", "F", "F'"],
                    "fill": True,
                },
                {
                    "lead": "B",
                    "bars": ["B", "A'", "A''"],
                    "foundation": "F",
                    "fbars": ["F", "F'", "F", "Fa"],
                    "response": True,
                    "fill": True,
                },
            ],
            "resolution": [{"lead": "A'''", "bars": ["A'''"], "foundation": "F''"}],
        }
    return {
        "introduction": [{"lead": "A", "bars": ["A"]}],
        "discovery": [
            {"lead": "A'", "bars": ["A'"]},
            {"lead": "A", "bars": ["A", "A'"], "foundation": "F''", "fbars": ["F''", "F"]},
        ],
        "convergence": [
            {
                "lead": "A",
                "bars": ["A", "A'"],
                "foundation": "F",
                "fbars": ["F", "F''"],
                "response": True,
            },
            {"lead": "A''", "bars": ["A''", "A"], "foundation": "F''", "fbars": ["F''", "Fa"]},
        ],
        "resolution": [{"lead": "A'''", "bars": ["A'''"]}],
    }
