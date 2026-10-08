# 11 — Testing and Evaluation

Nothing below has been run yet. Each item states its planned location; the final report must say which tests actually passed.

## Unit/integration (pytest, `server/tests/`)
| Area | Tests |
|---|---|
| Ingest | 44.1/48/16 kHz inputs → all normalized to 48 kHz mono; stereo downmix; silence → `RecordingRejected`; <3 s rejected; corrupted bytes → 422, no row; clipping flagged; duplicate upload → 409 + same id |
| DSP | synthetic sine (centroid≈f, flatness low), white noise (flatness high), click train 4 Hz (onset density 4/s ±0.2, times ±20 ms), glide (f0 ±1 st); **determinism:** two runs → identical JSON hash |
| Model adapter | contract test with a *fake* deterministic model (so CI needs no weights) + real-model smoke test marked `@slow` |
| Memory | fusion math with hand-computed fixtures; λ→0 with 0 exemplars equals base; novelty triggers on synthetic far point; contradictory label → quarantine; merge; delete recomputes prototype; persistence across process restart |
| Visual | same features → identical `geometry_hash`; different recordings → distance>ε; label change → geometry_hash unchanged, hue changes; SVG reloads identically |
| Atlas | adding a point leaves existing positions unchanged (≤ pinned tolerance); delete doesn't move others |
| Music | plan schema valid/invalid; same seed → identical master SHA-256; removing a recording's source changes master and removes its stem; peak ≤ −1 dBFS; no NaN; stems sum ≈ master (±1 LSB); onset alignment ≤ 5 ms |
| Narrative | every template's required events enforced; forbidden-verb lint; LLM output with an invented number is rejected |
| Failure | kill model mid-job → recording and annotation preserved; restart resumes the job |

## Learning evaluation (`eval/run_eval.py`)
Data: own field recordings (target ≥ 60 clips, ≥ 4 classes, ≥ 3 sessions) + an ESC-50 subset (license [M]: CC BY-NC; fine for local evaluation, not redistributed — VERIFY). Split by session. Protocol: for n ∈ {0,1,3,5} labelled exemplars/class, measure on held-out sessions: macro-F1, per-class P/R, top-1/top-3, ECE (10 bins), unknown-detection AUROC (hold out one class as "unknown"), latency/RSS. Headline = gain over n=0, excluding identical-clip recall. Output: `eval/reports/*.json` + a markdown table pasted into the README. A negative result is reported as is.

## Acceptance tests (e2e, Playwright with a fake mic file `--use-file-for-fake-audio-capture`)
**AT-1 Record→Classify→Correct→Learn→Visualize→Compose→Replay**
1. Record fake clip → Saved → synced → prediction visible ≤ 10 s.
2. Correct label → `MemoryUpdated`, memory_version +1.
3. Record second similar clip → its prediction now cites memory and differs from before (or confidence of the corrected label rises).
4. Restart server → memory and atlas identical.
5. Compose from ≥ 3 clips → master exists, determinism check passes, stems listed.
6. Replay export zip hash = original.
**AT-2 Offline queue:** with server unreachable record 2 clips; restore; both sync once (idempotent on retry).
**AT-3 Unknown flow:** a held-out-class clip yields `novel=true`; naming it creates a label and changes the atlas and composition plan.

## Real-world protocol (30 min, outdoors, 2 people)
Record 10 clips (3 locations, 2 sessions), phone only; log screen-on time vs session time; label 6; record 4 more; render composition; rate recognizability; note failures (wind, wildlife distance). Publish honest results.

## Environment verification (M0)
`scripts/verify_env.py` prints Python/OS/GPU/ffmpeg/model-download status and runs bench from doc 03.
