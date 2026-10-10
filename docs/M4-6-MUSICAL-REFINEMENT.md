# M4.6 — From sound collage to musical composition

Branch `feat/m4-6-musical-refinement` (from `44ceac6`; core commit `f28831d`, refinement pass 2026-10-10 on top) · Date 2026-10-09 / 10

| Status | Value |
|---|---|
| Engineering | **PASS** — new composer, quality report, API/UI plumbing; **183 server + 57 web tests pass** (re-run 2026-10-10, not copied from the earlier report); builds clean |
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
| beds | −14 dB base; quiet introduction (−5.5), receding in the convergence (−8.5), continuous within a section, resolution fades over up to 3 s | −16 dB base; gaps in each phrase's last bar, ducked 6 dB under the lead |
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

Before = the committed `f28831d` code (re-measured on 2026-10-10 and identical to the numbers first reported); after = with the §10 refinement pass.

| Set | Mode | Events | Most-reused fragment | Distinct fragments | Dynamic spread (dB) | Section RMS dBFS (intro/disc/conv/res, after) | Literal bar repeats | Max simultaneous foreground | Click candidates | ≈LUFS (after) | Flags |
|---|---|---|---|---|---|---|---|---|---|---|---|
| A | legacy | 53 → 53 | 4 → 4 | 15 → 15 | 11.7 → 11.7 | -29/-22/-17/-23 | 0.25 → 0.25 | 3 | 0 | -18.0 | – → – |
| A | organic | 29 → 33 | 10 → 4 | 5 → 10 | 5.0 → 7.0 | -23/-24/-18/-25 | 0.0 → 0.111 | 2 | 0 | -18.4 | – → – |
| A | composed | 71 → 77 | 18 → 7 | 10 → 17 | 7.7 → 6.7 | -26/-25/-19/-25 | 0.091 → 0.0 | 2 | 0 | -18.1 | – → – |
| B | legacy | 180 → 180 | 52 → 52 | 25 → 25 | 8.4 → 8.4 | -27/-22/-19/-25 | 0.462 → 0.462 | 5 | 0 | -18.1 | FOREGROUND, DENSITY, FATIGUE → FOREGROUND, DENSITY, FATIGUE |
| B | organic | 23 → 28 | 6 → 4 | 7 → 12 | 6.2 → 8.5 | -24/-25/-19/-28 | 0.143 → 0.143 | 2 | 0 | -19.2 | CLARITY → – |
| B | composed | 61 → 65 | 13 → 7 | 13 → 12 | 11.1 → 9.5 | -26/-29/-19/-26 | 0.222 → 0.222 | 2 | 0 | -18.2 | – → – |
| C | legacy | 86 → 86 | 7 → 7 | 17 → 17 | 10.1 → 10.1 | -29/-23/-19/-26 | 0.538 → 0.538 | 2 | 0 | -18.2 | REPETITION → REPETITION |
| C | organic | 57 → 57 | 14 → 6 | 7 → 10 | 6.3 → 8.4 | -28/-26/-21/-30 | 0.5 → 0.5 | 2 | 0 | -19.6 | – → – |
| C | composed | 150 → 143 | 35 → 11 | 15 → 16 | 8.0 → 10.4 | -27/-23/-21/-31 | 0.211 → 0.158 | 2 | 0 | -18.8 | FATIGUE → – |

What this does and does not show:

* **Structure improved where it was measurable** (all measurements, none a verdict on sound): foreground never exceeds 2 simultaneous attacks in the new modes (legacy B: 5); literal bar repetition is lower than legacy in A and B and C-composed; the "no air" flag of legacy B (foreground silent 15 %) is gone.
* **The refinement pass fixed the three weaknesses recorded at f28831d** (§10): the most-reused fragment fell from 18 / 13 / 35 (composed A / B / C) to 7 / 7 / 11; organic dynamic spread rose from 5.0 / 6.2 / 6.3 dB to 7.0 / 8.5 / 8.4 dB; the FATIGUE and CLARITY flags are gone.
* **Costs and open issues:** the composed pieces use fewer events than legacy (B: 180 → 65), a deliberate choice, not an improvement in itself; composed A's spread went *down* 1 dB (7.7 → 6.7) while its introduction became calmer; legacy B still carries its three original flags (it is the unchanged M4.5 baseline).
* **Source use:** with 4 sources all are used; with 8 the composer uses 6 (`SOURCES` flag) and the UI says which are unused.
* **None of these numbers says the music is better.** They show that obvious structural defects named in the review (overlapping foreground, literal repetition, no silence, one worn-out sample) were reduced.

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
| legacy | 3 × 30 / 5 × 60 / 8 × 60 | 44 / 122 / 232 | 0.10 / 0.14 / 0.22 s | 1.7 / 4.1 / 5.6 s | 0.05 / 0.07 / 0.09 | 417 / 859 / 1145 MB |
| organic | 3 × 30 / 5 × 60 / 8 × 60 | 28 / 57 / 55 | 0.12 / 0.19 / 0.32 s | 1.5 / 3.5 / 3.8 s | 0.05 / 0.06 / 0.06 | 440 / 820 / 915 MB |
| composed | 3 × 30 / 5 × 60 / 8 × 60 | 63 / 136 / 126 | 0.12 / 0.18 / 0.30 s | 1.8 / 3.8 / 4.8 s | 0.06 / 0.06 / 0.08 | 440 / 906 / 1007 MB |

The full comparison run (12 renders + diagnostics in one process) peaked at 796 MB RSS. "Analysis + plan" now includes material extraction. The new modes render faster simply because they place
fewer events. These are offline processing times, not playback latency.

## 7. Tests

| Suite | Result |
|---|---|
| `uv run pytest` (server) | **183 passed**, 1 deselected (`real_model`), 0 failed, 0 skipped (re-run 2026-10-10 after the refinement pass). 171 existed at `f28831d` (33 in `test_composer.py`, 4 new in `test_m4_api.py`, the rest M1–M4) and 12 are new in `tests/test_m4_6_refinement.py` (§10); one assertion in `test_composer.py` was changed on purpose (organic beds are now *continuous*, no longer *louder*, than composed beds). The real-ESC-50 integration tests run in the default (composed) mode. |
| `ruff check`, `ruff format --check`, `mypy unheard` | clean |
| `vitest` (web) | **57 passed** (mode toggle, default mode in the request, hierarchy chips, form/conversation/groove line) |
| `tsc --noEmit`, `vite build` | clean |

Two existing assertions on the schema version moved 4 → 5 (migration `0005_composition_mode.sql`).
Still **not** done: a real-browser run (see `M4-LISTENING-REVIEW.md` §3).

## 8. Remaining limitations

* **No one has listened.** Whether phrases are memorable, the answer is audible as an answer, or the groove feels human is unknown.
* All three sets get a **tonal lead** (bird, horn, bells). The horn was diagnosed (§10) as a *virtual* pitch (a two-tone chord tracked at its ~100 Hz common sub-harmonic), not an octave error, and is now placed by its audible partials; the bird lead went from 2 to 5 notes, using glides. A rhythm-led arrangement is exercised by the groove set, not by A/B/C.
* Fragment reuse is bounded (≤ 11 in the demo sets) by letting worn-out weak positions rest; that makes some composed pieces sparser (C: 150 → 143 events, and fewer weak hits in the groove).
* The dynamic arc is 7–10 dB in the new modes (legacy 8–12); organic remains quiet by design, and the introduction is bed-only.
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

## 10. Refinement pass (2026-10-10, after the core commit `f28831d`)

Verified starting state: `f28831d` exists locally, is the branch head, the tree was clean, and the code, migration `0005`,
API, UI, tests and this document were all present — so nothing was re-implemented. §8 of the core commit listed three
open weaknesses (fragment reuse, a flat organic arc, shaky pitch); this pass addresses exactly those. All numbers are
objective measurements from `scripts/m4_6_compare.py` (before = `f28831d`, re-measured), none says the music is better.

### A. Fragment repetition

*Cause (read from the code):* at accent positions the groove alternated between only the two best attacks
(`pool[:2]`, switching every two bars), so over ≈ 22 bars each of two samples sounded 20–35 times.

*Change:* a per-piece **fragment ledger** in the composer. For groove hits and fills the composer now chooses among the
source's good attacks (score ≥ 0.6 × best; the top 4 at accents, top 7 at weak positions) by `usage + 3 × (used in the last 5
hits) − 2 × quality`; if the best candidate has already sounded `cap = max(8, round(bars / 2))` times it widens to *every* real
attack of that source, least-used first; if even that is worn out, a **weak or ghost position rests** (silence) rather than
repeating. Ghost notes and fills go through the same ledger. Material extraction keeps up to 14 attacks per source (was 10).
Nothing unrelated is introduced: every fragment is still a window of the event's own recording (tested).

| | Most-reused fragment | Distinct fragments | Events |
|---|---|---|---|
| A composed | 18 → 7 | 10 → 17 | 71 → 77 |
| B composed | 13 → 7 | 13 → 12 | 61 → 65 |
| C composed | **35 → 11** | 15 → 16 | 150 → 143 |
| A / B / C organic | 10 → 4 / 6 → 4 / 14 → 6 | 5 → 10 / 7 → 12 / 7 → 10 | 29 → 33 / 23 → 28 / 57 → 57 |

### B. Organic dynamic development

*Causes:* organic beds were continuous and sat at about the same level in every section (the foreground section offsets
were also being added to the beds, so beds *rose* in the convergence), and the foreground had no shape inside a section.

*Changes (a gain shape, not a loudness change — every piece is renormalised to the same ≈ −18 LUFS):* beds now follow their own
absolute section offsets (organic: −5.5 / −6.0 / −8.5 / −8.0 dB, i.e. quiet introduction, **receding** when the foreground
enters; composed keeps its previous effective values); the foreground section offsets are −6.5 / −3 / +3.5 / −6.5 dB (organic);
a velocity **crescendo through the introduction, discovery and convergence phrases and a decrescendo through the resolution**
(0.9→1.0, 0.82→0.95, 0.85→1.0, 0.95→0.6); the organic **lead enters one bar after the bed** in the introduction; the final
resolution bed fades out over up to 3 s.

| Dynamic spread (dB) | before | after | section RMS after (intro/disc/conv/res, dBFS) |
|---|---|---|---|
| A organic | 5.0 | **7.0** | -23 / -24 / -18 / -25 |
| B organic | 6.2 | **8.5** | -24 / -25 / -19 / -28 |
| C organic | 6.3 | **8.4** | -28 / -26 / -21 / -30 |
| A / B / C composed | 7.7 / 11.1 / 8.0 | 6.7 / 9.5 / 10.4 | convergence is the loudest section in all six |

The climax is in the convergence in every set and mode. Composed A's spread fell 1 dB (the calmer introduction); it is the
one number that moved the other way.

### C. Pitch reliability

Three clips were probed (`car_horn`, `chirping_birds`, `church_bells`; ESC-50) before changing anything:

* **The horn is not an octave error.** Two horn clips track near 104 and 100 Hz while a third, clean one reads 487 Hz. A two-tone
  horn is periodic at the *common sub-harmonic* of its partials (e.g. 400 + 500 Hz → 100 Hz) although there is almost no energy
  there: a **virtual pitch**. The old register rule treated 100 Hz as the pitch and moved the whole motif **up an octave**, away
  from where the horn is heard. Fix: each tonal fragment records its strongest partial (`audible_midi`) and whether the pitch is
  virtual (partial > 2.6 × f0 and < 20 % of the peak energy at f0); the **register** is now chosen from where the motif is heard
  (`register_center_midi`). Intervals and the tonal centre are untouched. Measured: the two horn clips' audible register is
  MIDI 68 and 86 (≈ 415 Hz / 1.4 kHz) instead of 44; octave moves 1 → 0.
* **Bird glissandi** failed the 1-semitone wobble gate, leaving a 2-note motif. A second tier admits glides (confidence ≥ 0.85,
  ≥ 60 ms, ≤ 3 semitones of glide, within 14 semitones of the source's own centre) **only for a source that already has two
  tier-1 notes**. Usable notes: bird `1-34495` 2 → 5, `1-100038` 3 → 4, horn `1-24074` 2 → 3, bells `1-13571` 3 → 6.
* **Unchanged on purpose:** the 0.80 confidence gate for tier 1; octave folding; noise and clicks still produce no pitch and no
  key (tested for both tiers); no new pitch tracker; legacy mode's analysis is untouched.

### Verification

* New tests (`tests/test_m4_6_refinement.py`, 12): reuse cap and spread; reuse does not scale with length; determinism, order independence and
  provenance of fragments; organic arc (6–15 dB, climax in the convergence, ≥ 3 dB over both ends, LUFS held); organic bed recedes and the lead
  enters after the bed; crescendo/decrescendo across phrases; glide admission (tier 2); noise/clicks never tonal; virtual-pitch register;
  clean tone not virtual; the horn motif has no ±12 st leap; **legacy plan hash pinned** (`c11a2c61c6976f1e`, verified identical before and after
  this pass; the legacy master hash `a443377b0c8d00e6` also matched).
* Server 183 passed, web 57 passed, ruff / mypy / tsc / vite build clean. The earlier reported totals reproduced (171 server tests at `f28831d`
  + 12; 57 web).
* Resources: compare run peak 796 MB RSS; bench peaks 417–1145 MB per configuration (table in §6); all heavy runs sequential; no model loaded.
