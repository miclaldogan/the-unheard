# The music engine (M4 / M4.5 / M4.6)

> **M4.6 adds a second planner.** `mode=composed` (default) and `mode=organic` use the motif/phrase composer
> described in [`M4-6-MUSICAL-REFINEMENT.md`](M4-6-MUSICAL-REFINEMENT.md) (material → motif → phrase → section, hierarchy,
> call-and-response, groove, tonal gating, WSOLA pitch shifts). `mode=legacy` is the M4/M4.5 event planner described
> below, unchanged and bit-identical. Sections 1–10 describe that legacy planner and the shared renderer.

Everything here describes code that exists in `server/unheard/music/`. Versions:
`ANALYSIS_VERSION = 1`, `PLANNER_VERSION = 1`, `RENDER_VERSION = 1` (stored on every composition).

```
canonical WAV + M1 feature arrays ──► analysis.py ──► roles.py ──► planner.py ──► render.py ──► master + stems
        (48 kHz mono float)            measurements     role per      plan.json      offline NumPy/SciPy
                                                        source        (events)
```

`engine.compose()` is the pure pipeline; `service.py` wraps it with validation, a single-thread
background worker, atomic file writes, persistence and ECHO-0 lines.

## 1. Source analysis (`analysis.py`)

Reuses M1 arrays (RMS envelope, flatness, centroid, flux, onset strength, onset times, mel times)
and adds only what music needs:

| Measurement | Definition | Used for |
|---|---|---|
| onsets, density | M1 peak-picked log-mel flux; strength = local max of the novelty curve | percussion/accent roles, rhythm patterns |
| periodicity | strongest autocorrelation peak of the onset-strength curve in 0.25–2 s → `period_s`, strength 0–1 | tempo, pulse role |
| stability | 1 − CV of the linear RMS envelope over **all** frames (floored at −90 dBFS, so gaps between impulses count) | texture / drone vs hits |
| pitch | YIN (frame 2048, hop 1024, threshold 0.15, 80–4000 Hz); voiced only where the cumulative-mean difference < 0.2; runs ≥ 60 ms split at jumps > 2.5 semitones | tonal motif, key |
| segments | transient slices (onset −8 ms → next onset, ≤ 450 ms), one sustained window (steadiest loud 1–4 s), voiced runs | the *exact* source windows every event cuts |

Noise never yields pitch: `voiced_ratio ≈ 0` and no runs, so no key can be derived from it
(tested). Harmonic/percussive separation was **not** implemented; onset strength + stability +
voiced runs gave the same routing for this MVP. Power-domain spectral flatness is tilt-dominated
on real recordings (rain, wind and traffic all sit below 1e-3), so it is *not* used to decide
"noisy"; absence of pitch plus steadiness is.

## 2. Role assignment (`roles.py`)

Seven roles, each scored 0–1 from the measurements:

| Role | Evidence (summary) |
|---|---|
| percussion | ≥ 2 onsets; density and strength; discounted when the sound is steady |
| tonal_motif | voiced ≥ 8 % with ≥ 2 runs; within-note pitch wobble |
| rhythmic_texture | periodicity × steadiness; discounted when pitched |
| texture | steadiness × absence of pitch × (1 − percussion) |
| drone | steady and dark (centroid < 3 kHz) |
| accent | 1–3 strong isolated onsets, not steady |
| granular | noisy and unsteady |

The primary role is the best feasible score ≥ 0.30, otherwise the conservative default
(`texture`, or `granular` if there is no sustained window). A secondary role is kept only if
it scores ≥ 0.5 and ≥ 80 % of the primary. Roles that need material the source lacks (melody
without voiced runs, percussion without onsets) are never assignable. **Semantic labels are not
an input.** Manual override (`role_overrides`) is honoured only when feasible; otherwise the
measured role is used and the rationale says why. Every decision returns scores, evidence and a
one-line rationale, stored per composition source and shown in the UI.

On the 48 ESC-50 clips this produced (e.g.) rain/wind/vacuum → texture, footsteps/clock/water
drops → percussion, engine → pulse or percussion, church bells/car horn/some birds → melody;
two clips of the same label can land in different roles.

## 3. Composition grammar (`planner.py`)

* **Tempo:** strongest periodicity folded into 70–140 BPM; else median inter-onset interval;
  else a default 84 BPM "free time" (flagged). The *intensity* control then scales it by 0.92–1.08.
* **Length:** target 15–90 s (UI: 30/45/60/75), rounded to whole bars (+ 2.5 s reverb tail).
* **Sections:** introduction → discovery → convergence → resolution. Bar proportions start at
  20/26+/30+/20+ % and shift with the number of sources and how percussive/steady they are.
* **Layers:** one per (source, primary role), plus the secondary role when ≤ 3 sources; ordered
  atmosphere → drone → pulse → percussion → melody → accents → grain, ties by steadiness then
  content hash. Introduction plays layer 1; discovery adds half of the rest; convergence all;
  resolution returns to the foundation (and one more when ≥ 3 layers).
* **Spectral lanes:** atmosphere layers (texture/drone/granular) get separate bands ordered by
  measured centroid (≤ 1.2 kHz, 1.2–4.5 kHz, > 4.5 kHz) and each extra one is 3 dB lower, so two
  noise beds do not form one wall.
* **Events**
  * *texture/drone:* one crossfaded loop of the sustained window per section (drone plays an octave down, low-passed at 700 Hz).
  * *pulse:* one source cycle placed every 1–2 beats, resampled so its period equals the beat (rate clamped 0.7–1.4).
  * *percussion:* the source's **real onset sequence** is compressed or stretched onto a ≤ 4-bar grid pattern (the pattern moves, the audio does not); hits are ranked by strength and kept by *density*.
  * *accent:* the strongest transient at each section boundary after the first, at rate 0.8.
  * *tonal motif:* 3–8 notes from the strongest voiced runs; each run is tuned to the nearest tone of a minor-pentatonic scale built on the measured median pitch of the first tonal source (shift ≤ ±7 semitones) and moved down 1–2 octaves if it would sit above ≈ 1 kHz; phrases alternate with their reversal.
  * *granular:* a seeded grain cloud (90 ms Hann grains) over the sustained window.
* **Controls (all measurable):** *density* — fraction of hits/notes/grains kept; *structure* — 0 keeps natural micro-timing, 1 snaps events to the 16th grid; *intensity* — tempo ±8 %, section dynamics, filter brightness, climax level.
* **No key without pitch:** if no source is tonal there is no `key` and no melody.

## 4. Transformations (`render.py`)

Slice, loop (equal-power crossfade), grains. Per event: exact source excerpt → resample by
`rate` (Catmull-Rom cubic, with a 4th-order zero-phase anti-alias low-pass when rate > 1) →
gentle tanh crest softening of slices (peaks above 3× RMS) → 40 % loudness compensation towards
−24 dBFS (±6 dB; no per-source normalisation) → Butterworth low/high-pass → gain → raised-cosine
fades (≥ 1 ms in, ≥ 2 ms out) → equal-power pan → add into the track's stereo stem. Each stem
then gets a short synthetic reverb (decaying, low-passed noise impulse response seeded from the
composition seed; wet within the stem). The reverb impulse response is the **only synthetic
audio** and it only ever processes recorded material; there are no synthesised voices.

Not implemented: time-stretching (rate changes pitch *and* speed), spectral processing beyond
filters, stereo recordings (sources are mono).

### Arrangement ducking and level shaping (M4.5)

Atmosphere layers (texture, drone, grain cloud) duck by 4 dB under every slice of a percussion,
accent or melody layer (15 ms attack, hold ≤ 0.4 s, 250 ms raised-cosine release). The ducking
spec is stored in the plan (`ducking`) and applied to the stems before they are summed, so stems
still sum to the master. Sections with fewer sounding layers get +1.5 dB per missing layer
(≤ +6 dB) and the section offsets are −6 / −3 / 0 / −5 dB, which keeps the section-to-section
loudness spread near 11–12 dB instead of ~19 dB. Both were chosen from the diagnostics in
[`M4-LISTENING-REVIEW.md`](M4-LISTENING-REVIEW.md), not by ear.

## 5. Mixing and limiting

Master = Σ stems. One makeup gain moves integrated loudness towards −18 LUFS (BS.1770-style
K-weighted meter, 400 ms blocks, absolute −70 and relative −10 gates; computed here, not from a
reference meter), backing off until the limiter reduces ≤ 5 dB. A look-ahead (5 ms) smooth peak
limiter holds the sample peak at −1 dBFS; **the same gain envelope multiplies the master and every
stem**, so stems still sum to the master (test: max difference < 1e-9 in float). Output is 16-bit
48 kHz stereo WAV. No hidden resampling: sources must already be 48 kHz (the M1 canonical rate).

## 6. Determinism

* The plan is a pure function of (analyses, roles, seed, controls, duration, versions). Sources
  are ordered by **content hash**, not by database order or UUID; every random choice comes from a
  PCG64 stream seeded with `(seed, sha256(purpose-label))`. No global random state.
* `plan_hash` = SHA-256 over the plan with recording UUIDs removed, so the same audio produces
  the same hash in a different install.
* Rendering is NumPy/SciPy single-threaded float64. **Tested:** same audio + seed in two
  separate installs → identical `plan_hash` and identical master SHA-256 (same machine,
  same Python 3.12 / NumPy / SciPy). Across CPUs or library versions floating-point sums and
  FFT convolutions can differ in the last bits; the documented tolerance for those cases is
  "same plan_hash, master equal within 1 LSB of 16-bit PCM" — **not yet verified** on another
  platform.
* The request is idempotent: identical (sources, seed, controls, duration, overrides, versions)
  returns the existing composition (HTTP 200, `created: false`) instead of duplicating files.

## 7. Provenance

Every plan event carries `source` (content hash), `source_start_s`, `source_end_s`, `t`, `dur`,
role, track, kind and its transformation (`rate`, `pitch_shift_st`, `octave_shift`, `gain_db`,
filters, fades). They are stored in `composition_event`; `GET /api/compositions/{id}/trace/{seq}`
resolves composition → track → event → source recording → specimen (`artifact_id`,
`geometry_hash`) and lists other compositions using the same recording. Stems are exported
individually; the bundle contains `plan.json` and `provenance.json`.

## 8. Persistence, jobs, deletion

Migration `0004_orchestra.sql`: `composition`, `composition_source`, `composition_track`,
`composition_event`. Files live in `data/compositions/<aa>/<id>/{master.wav, stems/, plan.json,
provenance.json}`, written atomically; the row flips to `ready` only after every file exists, in
one transaction. A single worker thread renders one composition at a time (peak RSS ≈ 1.1 GB for
8 sources × 60 s); interrupted renders return to `queued` on start; a failed render deletes its
partial files, records the error and leaves the recordings untouched. **Deleting a recording
deletes every composition that contains it** (privacy: those files contain its audio), logging
`CompositionDeleted(reason=source_deleted)`.

## 9. ECHO-0 as conductor

Deterministic lines, each with its evidence: the "remembered separately" pair only for the first
ever ready composition; the shared-rhythm line only when two sources have periodicity ≥ 0.3 and
periods within 4 % (octave-folded); a role summary from the real role counts; the closing line
after a successful render. The optional Gemma planner is **not implemented** (see limitations).

## 11. M4.6 additions to the shared parts

* **Analysis v2:** voiced runs carry a YIN `confidence`; `material.py` ranks attacks (clarity, sharpness, isolation — not loudness), tonal runs (reliability gate), gestures, textures, beds and cycles.
* **Renderer:** `preserve_duration` events are pitch-shifted by resampling and then time-stretched back with WSOLA (`sola_stretch`) so a note keeps its length; ducking accepts per-trigger depths (`ducking.depths`); legacy plans render exactly as before (the loudness compensation is still measured on the source excerpt).
* **Plan fields (composer):** `mode`, `groove`, `motifs[]` (with `relation`), `phrases[]`, `form`, `conversation[]`, `hierarchy`, `foreground_dropped`; events add `hierarchy`, `motif`, `variation`, `phrase`, `fragment`, `velocity`, `ghost`, `fg_window_s`, `response_to`.
* **Quality report:** `music/quality.py` (`evaluate`) returns measurements and flags with a disclaimer; it is a diagnostic, not a score.

## 10. Known limitations

* **I could not listen to the output.** Quality was checked with measurements and spectrograms, not ears. The musical-quality gate is `NEEDS REVIEW`; see `docs/M4-REPORT.md` for the listening protocol.
* Noise-heavy source sets (rain + vacuum, rain + wind) still sound — by spectrogram — like a broadband wash with sparse events on top; spectral lanes help but do not make it dense music.
* Transient-heavy sources (footsteps, clock ticks) can make a steady grid of hits (urban set); the *density* and *structure* controls are the remedy.
* Pitch extraction is YIN on a 21 ms hop: bird chirps and car horns are sometimes tracked an octave or more off (e.g. a car horn reported near 100 Hz); the melody follows what was measured.
* Resampling changes pitch and speed together; a 2-octave move makes a chirp four times longer and darker.
* Mono sources only; no real-time engine; no time-stretch; byte-identity verified on one machine only.
