# 06 — Generative Music Engine

## Decision
A **deterministic Python renderer** (numpy/scipy) turns a validated *composition plan* + the player's WAVs into `master.wav` and per-recording stems. The browser only plays the rendered files. Tone.js / live Web Audio synthesis is deferred (ADR-006): offline render gives byte-reproducible output, easy tests, and trivial export. Trade-off: no live tweaking in MVP.

## Provenance rule
Every audible sample in the output is a transformed slice of a player recording, **or** a pure sine/filtered-noise bed generated from measured parameters. No bundled instrument samples. Each stem carries `source_recording_id`. Test: remove a recording → its stem disappears and the master changes measurably.

## Audio → music mapping
| Measured | Musical use | Guard |
|---|---|---|
| Onset times (IOI histogram) | Rhythm grid: tempo = IOI-histogram mode folded into 70–140 BPM; onsets quantised to 16ths with 50 % swing-preservation; each onset slice (80–250 ms) becomes a percussive hit | If <3 onsets use texture role instead |
| Spectral flatness high | **Noisy source ⇒ no pitch.** Gets percussion/texture role only | Prevents fake melody from wind/traffic |
| Flatness low and voiced ratio ≥ 0.4 | Melody: f0 contour → median-smoothed → quantised to a scale; the *recording itself* is pitch-shifted (granular / resample) to the target notes | Max shift ±7 semitones else use sine voice fallback |
| Spectral centroid | Register & ordering: low centroid → bass layer, high → upper layer | |
| RMS envelope | Dynamics: stem gain automation follows (smoothed) envelope; macro-intensity curve for sections | Master limiter −1 dBFS |
| Sound-to-sound contrast (embedding distance) | Arrangement: dissimilar recordings are placed in contrasting sections; near-duplicates are layered | |
| Atmosphere (long, low-flux, low-onset) | Pad: granular cloud (grain 60–120 ms, Hann, seeded jitter), low-pass filtered | |
| Key/scale | Scale from the strongest melodic recording's median f0 pitch class (else A minor pentatonic) | Seeded choice, recorded in plan |

Structure: 3 sections (Intro: textures only → Body: + rhythm + melody → Outro: strip back), 24–48 bars, length 45–90 s.

## Plan schema (contract: `contracts/composition_plan.schema.json`)
```json
{
  "version": 1, "seed": 123456, "tempo_bpm": 96, "key": "A", "scale": "minor_pentatonic",
  "sections": [{"name":"intro","bars":8}, {"name":"body","bars":16}, {"name":"outro","bars":8}],
  "tracks": [{
    "id":"t1","recording_id":"rec_…","role":"percussion|melody|pad|bass|texture",
    "source_window":[0.0, 4.2], "events":[{"t_beats":0.0,"dur_beats":0.25,"slice":[0.31,0.45],"pitch_shift_st":0,"gain_db":-6}],
    "filter":{"type":"lowpass","hz":6000}, "pan":-0.3, "active_sections":["body"]
  }]
}
```
Validated with JSON Schema + semantic checks (recording ids exist, slices in range, ≤ 8 tracks, ≤ 2000 events, gains ≤ 0 dB). Invalid plan ⇒ reject and fall back.

## Planner modes
1. **Deterministic planner (default, required):** pure function of features + seed.
2. **LLM planner (optional):** Gemma via Ollama receives a *compact JSON summary* (roles, tempo candidates, labels), returns a plan; schema-validated; on failure or timeout (20 s) → deterministic planner. The LLM may choose tempo/key/section layout/role assignment but **cannot reference audio that doesn't exist** and never renders audio itself.

## Listening modes
- **Original world:** play source recordings.
- **Inside the orchestra:** solo/mute each stem (stems rendered individually, summed = master within rounding).
- **Reconstructed world:** `master.wav`.

## Export & reproducibility
`composition_{id}.zip`: `master.wav` (44.1 kHz, 16-bit, stereo), `stems/*.wav`, `plan.json`, `provenance.json` (recording hashes, dsp/render versions, seed). Same inputs + versions + seed ⇒ identical master SHA-256 (tests run on one platform; cross-platform float differences are noted as VERIFY).

## Quality evaluation (objective, since taste isn't testable)
Peak ≤ −1 dBFS; no NaN; no clipping; per-stem non-silent; onset-alignment error of rendered percussion vs plan ≤ 5 ms; section loudness ordering (body ≥ intro). Subjective check: 3 listeners rate "recognisably made from these sounds" 1–5 [target avg ≥3, no claim until run].

## Latency [E]
Render 60 s stereo from ≤ 5 sources: expected a few seconds in numpy; measured in M4.
