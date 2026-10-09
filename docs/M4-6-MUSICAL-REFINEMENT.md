# M4.6 — From sound collage to musical composition

Branch `feat/m4-6-musical-refinement` (from `44ceac6`) · Date 2026-10-09

| Status | Value |
|---|---|
| Engineering | **PASS** — new composer, quality report, API/UI plumbing; 171 server + 57 web tests pass; builds clean |
| Musical quality | **NEEDS REVIEW** — nobody has listened to the new pieces. Everything about "better music" below is a structural claim backed by measurements, not an artistic one |
| Human listening | **PENDING** (§9) |

Scientific claims (what the code does, what was measured) and artistic claims (what it should sound
like) are kept apart: §3–§6 are the former, §1 and §9 the latter.

## 1. What human review said (qualitative, not ground truth)

* **Natural** — strong atmosphere, but drops and tonal events repeat without forming memorable phrases.
* **Urban** — interesting rhythmic material, but rigid timing and repetitive beat placement; mechanical.
* **Hybrid** — interesting contrasts, but competing elements with no musical conversation and no hierarchy.

## 2. Root causes in the M4/M4.5 engine (read from the code, not guessed)

| Symptom | Cause in `planner.py` / `render.py` |
|---|---|
| No memorable phrases | The planner scheduled **events**, not sentences. A melody was the source's voiced runs cycled in order (3–8 notes) and replayed reversed on alternate repeats; percussion replayed one source-derived bar pattern (`bar_hits[bar % n_pat]`) — literal repetition, no variation, no phrase boundaries, no recall in the resolution. |
| Mechanical timing | Hits were snapped by a single global `structure` mix (default 0.5) and every bar got the identical pattern. No accents, ghost notes, swing, fills, rests or micro-timing; velocity came only from onset strength. |
| No hierarchy / no conversation | All layers (up to 10) were equal citizens. Each section simply switched more layers on. Atmosphere ran continuously and ducked a uniform 4 dB; up to 5 attacks could sound at once (the urban set: 5, "FOREGROUND" flag). Layers were scheduled independently, so nothing could answer anything. |
| Shaky melodies | YIN gave octave errors (a car horn tracked near 100 Hz, birds at 2.2 kHz); every pitched run was used regardless of confidence; all were snapped to a pentatonic scale; moving a note changed its duration (resampling couples pitch and speed). |
| Rarely-heard sources | Fixed role table: whatever scored highest played in every section. |

## 3. What changed (algorithms)

Pipeline: **source recording → material → motif → phrase → section → composition**
(`music/material.py`, `music/composer.py`). Every stage keeps the exact source window.

1. **Material** (`extract_material`): ranked fragments per source — *attacks* (score = attack clarity over the preceding background + sharpness + isolation; **loudness is not an input**, tested by scaling the input), *tonal* runs (usable only with YIN confidence ≥ 0.80, ≥ 80 ms, wobble ≤ 1 semitone), a *gesture* (the attack with the most unusual spectral centroid), a short *texture*, a long *bed*, a periodic *cycle*.
2. **Motifs**: a rhythm motif is a window of the source's **real onset sequence** (relative timing kept) mapped near its own pulse; a tonal motif is 2–5 reliable pitched fragments in source order; gesture/swell/cycle motifs for the rest. Motifs are short (≤ 8 notes).
3. **Variation operators with a recorded relation to the parent**: `shift` (syncopation), `density` (drop weakest / add ghost notes), `fragment` (another real fragment of the same source at the same positions), `register` (octave, intervals preserved), `retrograde`, `answer` (question half). Each plan lists `motifs[]` with `relation = {parent, operator, …}`.
4. **Phrases and form**: 4-bar phrases (a remainder is merged; never a 1-bar orphan). Each section has recipes such as *A A' B* per bar for rhythmic leads or *A / A' / A'' (retrograde) / B (octave)* for tonal leads; the groove cycles `F F' F Fa`; the **last bar of a phrase rests** (the lead stops) and beds leave air there. Introduction = present A; discovery = vary and answer; convergence = A, F and the answer together; resolution = recall A as the question half (`A'''`) over a thinned groove.
5. **Hierarchy**: lead / foundation (groove) / support (answer) / gesture / bed. A source is a bed **or** a voice, never both. Beds are chosen first (steady material: stability ≥ 0.45), band-limited per lane, ducked 3–6 dB under foreground attacks, with gaps. `enforce_foreground` guarantees ≤ 2 foreground attack windows at any instant (lowest priority dropped first).
6. **Call-and-response**: candidates (other rhythmic, cycle or pitched sources) are scored from evidence — temporal fit into the lead's rests, spectral contrast (centroids), tonal consonance of the two tonal centres, pulse relation of the periods — and the best (score ≥ 0.45, up to 3, taking turns) answers **after** the lead's last note, never over it; the groove thins around the answer (events within ±1.5 steps dropped, others −4 dB). The evidence is stored in `conversation[]` and surfaced by ECHO-0 only when answered events exist.
7. **Groove**: `groove_q` ∈ [0,1] mixes source timing (0) and the 16th grid (1). Swing delays odd 16ths (`swing_steps`), accents follow metrical weight × attack quality, the quietest weak-position hits become ghost notes (−10 dB, shorter, rotating through the source's real attacks), seeded Gaussian micro-timing is clipped to ±14 ms and never touches downbeats, fills (4 sixteenths) precede some phrase ends, hit fragments rotate through the source's best attacks at weak positions and alternate between the two best on accents. Compared modes: source-timed (0), hybrid (default 0.6 in composed), quantised (1); documented in §5.
8. **Tonal coherence**: reliability gate (above); `octave_folded` — a run that is ±12 st from the tonal centre with confidence < 0.92 is treated as an octave error and folded to the centre's octave for **targeting**; the whole motif moves by whole octaves only if the centre is outside E3–F♯6 (not 2 octaves like before); notes within 35 cents of a semitone are nudged ("tuned"); no scale snapping by default (`tonal_strategy="contour"`; `"pentatonic"` is kept for comparison). Pitch moves of ≥ 1 semitone use a **WSOLA time-stretch (`sola_stretch`) to keep the note's length** (tested: 440 Hz → 880 Hz keeps its duration ±6 % and pitch ±4 %). Noise and unreliable sources get **no** pitch and no key.
9. **Modes** (`mode` on the composition: `organic`, `composed`, and `legacy` = the unchanged M4/M4.5 planner):

| | ORGANIC | COMPOSED |
|---|---|---|
| groove | 10 % toward the grid (+30 % × structure), no swing, 10 ms micro-timing | 35 % (+50 % × structure; default 60 %), swing 0.22, 5 ms |
| phrases | irregular 3–5 bars | 4 bars, fixed |
| foreground | lead −5 dB, groove 55 % of its notes, no ghosts, no fills | lead −4 dB, full groove, ghosts and fills |
| beds | −14 dB, forward and continuous per section | −16 dB, gaps in each phrase's last bar, ducked 6 dB under the lead |
| conversation | only in the convergence | scheduled in discovery and convergence |

Both use the same real recordings, neither involves an LLM, and the UI exposes them as two buttons.

Environmental authenticity: only recorded material is played (the single synthetic element remains the
reverb impulse response applied to it); every event keeps `source`, `fragment`, `source_start_s/end_s`,
`motif`, `variation`, `phrase`, `hierarchy`, `velocity`, so the existing trace endpoint and the Original /
Transformed layer / Full comparison work unchanged.

## 4. How composition quality is evaluated (`music/quality.py`)

A transparent report, **not one score**: motif recurrence/variation, rhythmic diversity (distinct bar
patterns, literal repeat ratio, step-occupancy entropy), phrase structure, silence and density,
foreground clarity (max simultaneous foreground, per-hit clarity vs the other layers), spectral
masking, dynamic development, source contribution, click candidates, repetition fatigue (adjacent-bar
spectral similarity, most-reused fragment). Thresholds that raise flags are documented guesses. The
report ends with a disclaimer; human listening is the artistic gate.

## 5. Measured differences (objective, real ESC-50 clips, seed 7, 40 s target)

Source sets are the M4/M4.5 ones: **A** water drops + birds + wind + rain, **B** footsteps + engine + car
horn + clock, **C** rain + church bell + footsteps + vacuum. LEGACY is the unchanged M4.5 planner and
renders **bit-identical audio** to the M4.5 demos (checked). Each mode makes its own plan (tempo,
form and length differ slightly), so the comparison is controlled by sources, seed and loudness, not by
content. Numbers come from `scripts/m4_6_compare.py` → `server/data/m4_6/report.json`.

| Set | Mode | Events | Foreground events/bar | Distinct bar patterns | Literal bar repeats | Foreground silent share | Max simultaneous foreground | Spectral overlap | Worst hit clarity (dB) | Section loudness spread (dB) | Most-reused fragment | Click candidates | ≈LUFS | Flags |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A | legacy | 53 | 3.29 | 6 | 0.25 | 0.629 | 3 | 0.212 | 2.1 | 11.7 | 4 | 0 | -18.0 | – |
| A | organic | 29 | 1.57 | 7 | 0.0 | 0.812 | 2 | 0.235 | 1.4 | 5.0 | 10 | 0 | -18.0 | – |
| A | composed | 71 | 4.57 | 10 | 0.091 | 0.562 | 2 | 0.251 | 9.2 | 7.7 | 18 | 0 | -18.2 | – |
| B | legacy | 180 | 13.85 | 7 | 0.462 | 0.149 | 5 | 0.514 | -1.6 | 8.4 | 52 | 0 | -18.1 | FOREGROUND, DENSITY, FATIGUE |
| B | organic | 23 | 1.46 | 6 | 0.143 | 0.865 | 2 | 0.447 | -6.0 | 6.2 | 6 | 0 | -18.5 | CLARITY |
| B | composed | 61 | 4.38 | 7 | 0.222 | 0.697 | 2 | 0.363 | -1.6 | 11.1 | 13 | 0 | -18.4 | – |
| C | legacy | 86 | 3.59 | 6 | 0.538 | 0.574 | 2 | 0.555 | 4.5 | 10.1 | 7 | 0 | -18.2 | REPETITION |
| C | organic | 57 | 2.27 | 7 | 0.5 | 0.741 | 2 | 0.542 | 1.8 | 6.3 | 14 | 0 | -18.6 | – |
| C | composed | 150 | 6.36 | 15 | 0.211 | 0.443 | 2 | 0.549 | 8.5 | 8.0 | 35 | 0 | -18.6 | FATIGUE |

What this does and does not show:

* **Structure improved where it was measurable:** foreground never exceeds 2 simultaneous attacks (legacy B: 5); literal bar repetition fell in A (0.25 → 0.09) and B (0.46 → 0.22) and C-composed (0.54 → 0.21); distinct bar patterns rose in A and C; B-legacy's "no air" flag (foreground silent 15 %) is gone (70 %). The answer/hit clarity is higher in A and C (up to +9 dB).
* **It also shows costs and failures:** the composed pieces use fewer events (B: 180 → 61) — a deliberate choice, not an improvement in itself; organic B still has an answer at −6 dB under the other layers (flag `CLARITY`); composed C reuses one footstep fragment 35 times (flag `FATIGUE`) even with fragment rotation; the dynamic spread is *smaller* in the new modes (5–11 dB), i.e. less of an arc, which is possibly a weakness.
* **Source use:** with 4 sources all are used; with 8 the composer uses 6 (`SOURCES` flag) and the UI says which are unused.
* **None of these numbers says the music is better.** They show that obvious structural defects named in the review (overlapping foreground, literal repetition, no silence) were reduced.

Groove comparison (a rhythm-led urban set: footsteps, clock, engine, rain; COMPOSED mode):

| Groove | quantisation | off-grid share | distinct bar patterns | literal bar repeats |
|---|---|---|---|---|
| source-timed | 0.0 | 0.246 | 7 | 0.417 |
| hybrid (default) | 0.6 | 0.218 | 7 | 0.417 |
| quantised (swing + micro-timing remain) | 1.0 | 0.134 | 7 | 0.417 |

Only the timing differs, as designed. The chosen default is **hybrid** (60 % toward the grid plus swing and
5 ms micro-timing): hypothesis: source-timed keeps the recording's own feel but may wander against the other layers, while fully
quantised is what the review called mechanical. Which is better is for the listening session to decide, not a result.

Pitch-handling comparison (contour vs pentatonic) exists as `tonal_strategy` and is covered by tests; it was
**not** judged musically, only measured as "does pentatonic remap pitches and contour not" (it does).

## 6. Performance (i7-13700H, 15 GiB shared with other applications, Python 3.12.7, CPU)

`scripts/m4_bench.py` (each configuration in a fresh process, memory-capped):

| Mode | Sources × target | Events | Analysis + plan | Render | × real time | Peak RSS |
|---|---|---|---|---|---|---|
| legacy | 3 × 30 / 5 × 60 / 8 × 60 | 44 / 122 / 232 | 0.17 / 0.13 / 0.28 s | 2.1 / 6.2 / 7.0 s | 0.07 / 0.10 / 0.11 | 410 / 850 / 1140 MB |
| organic | 3 × 30 / 5 × 60 / 8 × 60 | 24 / 51 / 50 | 0.13 / 0.13 / 0.26 s | 1.4 / 2.7 / 2.8 s | 0.04 / 0.04 / 0.04 | 435 / 810 / 1006 MB |
| composed | 3 × 30 / 5 × 60 / 8 × 60 | 56 / 129 / 118 | 0.09 / 0.13 / 0.20 s | 1.0 / 2.1 / 2.8 s | 0.03 / 0.03 / 0.04 | 435 / 807 / 1000 MB |

"Analysis + plan" now includes material extraction. The new modes render faster simply because they place
fewer events. These are offline processing times, not playback latency.

## 7. Tests

| Suite | Result |
|---|---|
| `uv run pytest` (server) | **171 passed**, 1 deselected (`real_model`), 0 failed, 0 skipped. New: 33 in `test_composer.py` (deterministic material extraction; loudness-independent ranking; noise never tonal; low-confidence pitch gated; octave folding and register rules; pentatonic vs contour; every variation operator's relation; phrases/form/variation; provenance windows; regeneration stable and order-independent; call-and-response after the call, evidence-based; silence/rest bars; ≤ 2 foreground; swing and micro-timing bounds; groove modes differ; ORGANIC vs COMPOSED differ; a source is a bed or a voice; single-source plan; WSOLA keeps length and pitch; renderer compatibility, stems sum to master, no clicks; transparent quality report) and 4 in `test_m4_api.py` (modes, default, dedupe, variation inherits the mode, conductor line, trace metadata). The real-ESC-50 integration tests run in the default (composed) mode. |
| `ruff check`, `ruff format --check`, `mypy unheard` | clean |
| `vitest` (web) | **57 passed** (mode toggle, default mode in the request, hierarchy chips, form/conversation/groove line) |
| `tsc --noEmit`, `vite build` | clean |

Two existing assertions on the schema version moved 4 → 5 (migration `0005_composition_mode.sql`).
Still **not** done: a real-browser run (see `M4-LISTENING-REVIEW.md` §3).

## 8. Remaining limitations

* **No one has listened.** Whether phrases are memorable, the answer is audible as an answer, or the groove feels human is unknown.
* All three sets get a **tonal lead** (bird, horn, bells). The horn is tracked near 100 Hz (probably an octave error that the register rule moves up); the bird lead is only 2 notes. A rhythm-led arrangement is exercised by the groove set, not by A/B/C.
* Fragment reuse is still high in composed C (35×, one footstep sample) and A (18×).
* The dynamic arc in the new modes is flatter (5–11 dB spread); organic is quiet by design.
* With more than ~6 sources some are unused; the composer prefers selective arrangement over using everything.
* Pitch tracking is YIN on a 21 ms hop: bird glissandi and horn partials remain error-prone; WSOLA shifts of more than an octave on noisy sources will sound processed.
* The shared-pulse/"related rhythm" ECHO-0 line and the new "answered in the silence" line are statements of measured evidence, not of musical judgement.
* Cross-platform byte identity is still verified only on this machine.

## 9. Pending human listening (nothing here is marked PASS)

All files are under `/home/misa/projects/dev-challanges/the-unheard/server/data/m4_6/` and are
git-ignored (ESC-50: CC BY-NC 3.0, local evaluation only; **do not publish or redistribute**).

* `AB/<set>_<mode>.wav` — 25 s, **matched to −20 LUFS (integrated)**, convergence section + 8 s lead-in, for `A_natural`, `B_urban`, `C_hybrid` × `legacy` (= M4.5, bit-identical), `organic`, `composed` (9 files, 4.80 MB each).
* `AB/B2_urban_rhythm_groove_{source_timed,hybrid,quantized}.wav` — the groove comparison (3 files).
* `<set>/<mode>/master.wav` (full pieces, ≈ 43 s), `stem_t<N>.wav` (individual layers), `plan.json` (every event and its source window) — `report.json` has all measurements and the track roles.
* Regenerate everything: `cd server && PYTHONPATH=../scripts uv run python ../scripts/m4_6_compare.py` (needs the ESC-50 clips, see `eval/README.md`).

Listening protocol: for each set listen to legacy → organic → composed **at the same volume**, headphones first.
Score 1–5 (5 = best) and add a sentence where it matters:

| Question | A organic | A composed | B organic | B composed | C organic | C composed | Notes |
|---|---|---|---|---|---|---|---|
| Is there a recognisable idea (motif) you could hum or tap back? | | | | | | | |
| Does it develop/answer rather than just loop? | | | | | | | |
| Is there a clear foreground at each moment? | | | | | | | |
| Does it breathe (silence, rests)? | | | | | | | |
| Does the groove feel human, not mechanical? (B especially) | | | | | | | |
| Can you still hear the original world in it? | | | | | | | |
| Better than the M4.5 version of the same set? (yes / no / different) | | | | | | | |
| Overall enjoyment | | | | | | | |

Plus: which mode would you ship as the default? Does the melody (bird / horn / bells) sound like a
melody or like processed noise? What is the single worst thing you hear?

**Human feedback: none received yet.**
