# M4 Implementation Report — The Impossible Orchestra

Date: 2026-10-09 · Branch: `feat/m4-impossible-orchestra` (from `main` @ `9145a10`, M3 merged)

**Engineering status: PARTIAL.** The backend (analysis, roles, planner, renderer, persistence,
API, jobs) is complete and tested. The Orchestra UI is built, type-checked and tested in jsdom
with a fake Web Audio context, but **it has not been run in a real browser** (the Chrome
extension was not connected in this session), so real `decodeAudioData`/playback and the canvas
visuals are unverified.

**Musical quality status: NEEDS REVIEW.** I cannot listen to audio. Quality was assessed with
automated measurements and by looking at spectrograms; nothing below claims it *sounds* good.
The rendered WAVs are kept for a human to listen to (see "Listening protocol").

Optional Gemma planner: **not implemented** (deferred, extension point documented in
`docs/music-engine.md` §9). The app and every test run without it.

## What exists

| Area | Where |
|---|---|
| Source analysis (onsets, periodicity, stability, YIN pitch, segments) | `server/unheard/music/analysis.py` |
| Role assignment with evidence + manual override | `music/roles.py` |
| Deterministic planner (sections, layers, lanes, events, controls) | `music/planner.py` |
| Offline renderer (slice/loop/grains, filters, reverb, limiter, LUFS, metrics) | `music/render.py` |
| Pure pipeline | `music/engine.py` |
| Service: validation, idempotent create, worker, atomic files, cascade delete, ECHO-0 lines | `music/service.py` |
| Migration 0004 + repos | `storage/migrations/0004_orchestra.sql`, `storage/repos_m4.py` |
| API | `api/compositions.py`, `api/schemas_m4.py` (documented in `docs/api.md`) |
| Orchestra UI, Web Audio stem player, atlas selection + live glow | `web/src/components/Orchestra.tsx`, `web/src/audio/orchestra.ts`, `Atlas.tsx` |
| Demos and benchmarks | `scripts/m4_demo.py`, `scripts/m4_bench.py` |

Design write-up: [`docs/music-engine.md`](music-engine.md).

## Real musical behaviour

Everything audible is a transformed excerpt of a player's recording; the only synthetic audio is
a reverb impulse response applied *to* those excerpts. Roles come from measurements
(`roles.py`), never from labels. Real examples from the 48 ESC-50 clips tried (rain/wind/vacuum
→ atmosphere; footsteps/clock/water drops → percussion; engine → pulse; bells/horn/bird →
melody; two clips with the same label can get different roles):

* **Footsteps** contribute their *actual onset sequence* (compressed onto a bar grid), and the
  hit audio is the real footstep slices.
* **Bird/bell/horn** contribute voiced runs; each is tuned (≤ ±7 semitones) to the nearest note
  of a pentatonic scale built from the measured pitch, and moved down octaves when very high.
* **Engine** contributes one measured cycle placed on the beat (its period sets the tempo).
* **Rain/wind/vacuum** contribute the steadiest 4 s window, looped with crossfades, each in its
  own spectral lane.
Controls Sparse↔Dense, Organic↔Structured, Calm↔Intense change event counts, timing grid
alignment and tempo/dynamics respectively; each has a test.

## Audio quality

**Automated (real ESC-50 clips, seed 7, 40 s target, 3 sets of 4 sources, same machine):**

| Set | Roles (from measurements) | BPM (source) | Peak | ≈LUFS | Clip | Silence | Limiter max | Section RMS (dBFS) intro/disc/conv/res | Layer share |
|---|---|---|---|---|---|---|---|---|---|
| A natural: water drops, birds, wind, rain | percussion, melody, 2× atmosphere | 83.3 (periodicity) | −1.0 | −18.0 | 0 | 4.9 % | 0.5 dB | −36 / −25 / −17 / −29 | 0.18 / 0.30 / 0.16 / 0.35 |
| B urban: footsteps, engine, car horn, clock | 2× percussion, pulse, melody | 76.9 (periodicity) | −1.0 | −18.2 | 0 | 5.1 % | 4.4 dB | −33 / −25 / −18 / −30 | 0.29 / 0.24 / 0.22 / 0.25 |
| C hybrid: rain, church bell, footsteps, vacuum | 2× atmosphere, melody, percussion | 129.0 (onset intervals) | −1.0 | −18.2 | 0 | 5.1 % | 2.1 dB | −36 / −27 / −19 / −32 | 0.22 / 0.23 / 0.21 / 0.35 |

No empty sections, no events out of bounds, bar-envelope similarity 0.91–0.95 (not flagged
repetitive). The meter is a BS.1770-style implementation written here; it is not a calibrated
reference.

**Spectrogram inspection (what I saw; not what I heard).** All three show the intended arc:
quiet introduction, rising density, a loud convergence, a thinner resolution (RMS −36→−17→−29 dBFS).
A: low-band atmosphere in the introduction, thin pitched lines of the bird melody in the middle,
water-drop ticks throughout. B: a very regular grid of vertical hit lines dominates; it will
probably feel mechanical. C: still mostly a broadband wash with weak footstep and bell traces —
the weakest result. A first version of the mix was a continuous noise wall and over-limited by
10–12 dB; the loudness back-off, crest softening and spectral lanes were added after seeing that.

**Listening: pending.** I did not hear any of it. A human should answer for each set:
beginning/development/end? musical intention? layers distinguishable? source character
surviving? clicks or harsh artifacts? do A, B and C sound different?

### Listening protocol

```bash
cd server && uv run python ../scripts/m4_demo.py       # needs the ESC-50 clips (eval/README.md)
# → server/data/m4_demo/{A_natural,B_urban,C_hybrid}_master.wav, per-layer *_t1..t4.wav, *_plan.json, report.json
```
The files are git-ignored (ESC-50 is CC BY-NC 3.0, local evaluation only; not redistributed).

## Demonstration and validation

* Reproducible demo: `scripts/m4_demo.py` (above). The API path was also exercised against a
  live `unheard serve` process with real uploads: create → render → `GET /export` (200,
  `audio/wav`, 16-bit 48 kHz stereo, 6.2 MB) and a `Range` request (206).
* Real-audio integration test (`tests/test_m4_real_audio.py`, skipped when ESC-50 is absent): real
  recordings → DSP → roles → plan → render → persisted WAV → trace through the API; also byte-identical
  masters from two separate installs and different results for the urban set.
* Not done: a real-browser smoke test; phone test; Firefox; a human listening pass.

## Tests

| Suite | Result (2026-10-09) |
|---|---|
| `uv run pytest` (server) | **132 passed, 1 deselected** (`real_model`, needs CLAP weights), 0 failed, 0 skipped — includes 23 music-engine, 13 composition-API, 2 real-audio (4 cases) tests |
| `ruff check` / `ruff format --check` / `mypy` | clean / 83 files formatted / clean (60 source files) |
| `vitest` (web) | **55 passed** (8 files): player clock/seek/pause/mute-solo/ended, activity mapping, Orchestra flows (compose, mute/solo, play/seek, trace, compare, failed render + retry, save/export, atlas activity), Atlas selection |
| `tsc --noEmit`, `vite build` | clean, ok (236 kB JS) |

M1–M3 tests all still pass; two existing assertions about the schema version were updated
(3 → 4). One real regression was caught by the existing Atlas test and fixed: a default `[]`
prop re-created every render and looped the atlas.

Covered by tests: same input + seed → same plan; input order irrelevant; different seeds valid;
empty/over-large selection rejected; events reference valid source windows; noise never becomes
melody or a key; controls have measured effects; stems sum to the master; no NaN/clipping;
event edges start and end at zero; resampling length; equal-power pan; limiter ceiling; loudness
meter; idempotent create; variations; restart persistence; export (WAV + bundle); failure keeps
recordings and retry works; interrupted render re-queued; composition delete removes files;
recording delete cascades; every event traceable to an existing source.

## Performance (i7-13700H, 15 GiB RAM, Python 3.12.7, CPU only, `scripts/m4_bench.py`)

| Sources × target | Piece | Events | Analysis + plan | Render | × real time | Peak RSS | Master WAV |
|---|---|---|---|---|---|---|---|
| 3 × 30 s | 28.8 s | 44 | 0.10 s | 1.5 s | 0.05 | 402 MB | 6.0 MB |
| 5 × 60 s | 60.5 s | 122 | 0.14 s | 4.1 s | 0.06 | 835 MB | 12.1 MB |
| 8 × 60 s | 60.5 s | 232 | 0.22 s | 5.5 s | 0.09 | 1115 MB | 12.1 MB |

"Analysis + plan" excludes the M1 DSP (done at upload). Rendering is offline; these are
processing times, not playback latency. Startup impact: no model or library is loaded at
startup (SciPy is imported with the app). UI playback stability is unmeasured (no browser).
Renders are serialised on one worker thread to bound memory.

## Data and API

Migration `0004_orchestra.sql`. Endpoints (all under `/api`, token-guarded like the rest):
`POST /compositions`, `GET /compositions[?recording_id=]`, `GET|PATCH|DELETE /compositions/{id}`,
`POST /compositions/{id}/variation`, `POST /compositions/{id}/render`,
`GET /compositions/{id}/events`, `GET /compositions/{id}/trace/{seq}`, `GET /compositions/{id}/master`,
`GET /compositions/{id}/stems/{track}`, `GET /compositions/{id}/export[?bundle=true]`.
Events: `CompositionCreated|Planned|Rendered|Failed|Revised|Deleted`.

## UI

New **Orchestra** view: pick sources (or choose them in the Atlas with "Choose sounds for an
orchestra"), three sliders + length, Compose, Another variation, Save (name), Export WAV / bundle.
The stems play on one Web Audio clock (mute/solo are gain changes). Each layer shows its
specimen, role chip and when it enters; a canvas timeline draws the real events (click one →
"Where did that sound come from?", click empty space → seek). Compare: original recording /
transformed layer (solo) / full composition. During playback each specimen's brightness follows
its events, its animation follows the **source** position of the excerpt being heard, and the
atlas nodes glow while their recordings sound; `prefers-reduced-motion` disables easing and
animation. Specimen base geometry is untouched.

## Compromises and limitations

* No real-browser run, no listening, no phone test; musical quality is therefore unproven.
* Gemma/LLM planner deferred; ECHO-0 lines are templates with evidence.
* Source sets dominated by broadband noise stay wash-like; transient-heavy sets sound grid-like (see `music-engine.md` §10).
* Byte-identical output is verified on one machine; cross-platform tolerance is stated, not measured.
* Mono sources only; no time-stretch; resampling moves pitch and speed together.
* Deleting a recording deletes compositions made from it (privacy choice); there is no "keep" option.
* Specimen/atlas reactions are driven by `requestAnimationFrame` and a 60 ms atlas timer; frame times were not measured.

## Git

Branch `feat/m4-impossible-orchestra`, one local commit, **not pushed**. ESC-50 clips, rendered
WAVs, the SQLite database and `node_modules` are not committed.

## M5 readiness

The narrative layer can already consume: the append-only `event` table (`CompositionCreated|
Planned|Rendered|Failed|Revised|Deleted` with `composition_id`, `plan_hash`), per-composition
role decisions and measured evidence (`composition_source.decision_json`), shared-rhythm
evidence (periods) used by the conductor lines, specimen links (`trace`), M2 memory events and
M3 atlas states. ECHO-0's `echo_lines()` already states only what the evidence licenses; M5 can
move it into the shared narrative state machine and, optionally, let Gemma rephrase under the
same preconditions.
