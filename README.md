# THE UNHEARD

*An orchestra made of a world you almost forgot to hear.*

An open-source, local-first experience for the Hacktoberfest 2026 Open-Source AI Challenge
(Week 1, *Touch Grass*). You teach an amnesiac machine, ECHO-0, to hear by recording the real
world; its memory, atlas, artwork and music are built from your recordings.

## Status

**M4.6 (musical refinement, in progress on `feat/m4-6-musical-refinement`):** the orchestra can now be composed in two modes — **Composed** (motifs → phrases → sections, a clear foreground, call-and-response, swing and ghost notes) or **Organic** (source-timed, sparse and atmospheric) — in addition to the unchanged M4/M4.5 planner (`legacy`). Structure improved on objective measures; **nobody has listened to it yet**. See [`docs/M4-6-MUSICAL-REFINEMENT.md`](docs/M4-6-MUSICAL-REFINEMENT.md).

**M4 — the Impossible Orchestra: implemented (engineering PARTIAL, musical quality NEEDS
REVIEW).** Pick several sound memories (in the list or in the atlas), press Compose, and a
deterministic planner turns their *measured* acoustics into sections, layers, rhythm and (when
something is genuinely pitched) a melody; an offline renderer cuts, resamples, filters and mixes
the actual recordings into a 48 kHz stereo piece with per-layer stems. You can solo/mute layers,
compare original ↔ transformed layer ↔ full piece, click any event to trace it back to the exact
second of the recording it came from, regenerate with a new seed, save, reopen after a restart
and export the WAV. Specimens and atlas nodes react while their recordings sound. See
[`docs/M4-REPORT.md`](docs/M4-REPORT.md) and [`docs/music-engine.md`](docs/music-engine.md).

Honest about M4: nobody has listened to it yet (it was checked with measurements and
spectrograms), the Orchestra UI was not run in a real browser in this session, and the optional
Gemma planner is not implemented.

Earlier milestones: M1 real audio foundation ([`docs/M1-REPORT.md`](docs/M1-REPORT.md)), M2
real hearing (LAION-CLAP) and personal memory ([`docs/M2-REPORT.md`](docs/M2-REPORT.md)), M3
specimens and atlas ([`docs/M3-REPORT.md`](docs/M3-REPORT.md)).

Still not there: free narration (ECHO-0 lines are templates bound to events), fine-tuning, and
anything real-time (the music engine renders offline).

## Architecture summary

Modular monolith (docs/architecture/02): one FastAPI process with internal packages
`ingest → dsp → models (CLAP adapter) → memory (kNN + fusion) → visual (specimen params) → atlas (graph + layout) → music (analysis → roles → planner → renderer) → storage/events/jobs → api`,
SQLite (WAL) + content-addressed files under `data/`, and a Vite/React PWA. Processing is
durability-first: the raw upload and the recording row are committed before any processing;
the `dsp` and `infer` stages run on an in-process worker thread polling a `job` table;
failures leave the recording inspectable and retryable. Full design:
[`docs/architecture/README.md`](docs/architecture/README.md); decisions in
[`14-ARCHITECTURE-DECISIONS.md`](docs/architecture/14-ARCHITECTURE-DECISIONS.md) (ADR-013…016 for M2, ADR-017…019 for M3, ADR-020…022 for M4).

```
the-unheard/
  server/unheard/   api/ ingest/ dsp/ models/ memory/ visual/ atlas/ music/ jobs/ events/ storage/  (+ app.py, cli.py, config.py)
  server/tests/     DSP, ingest, API, memory/fusion, migration, e2e, real-model tests + fixtures
  web/src/          api/ audio/ state/ visual/ components/  (React + TS)
  eval/             run_eval.py, reports/
  scripts/          mkcert.sh, verify_env.py, bench_models.py, m4_demo.py, m4_bench.py
  docs/             api.md, model-setup.md, visual-grammar.md, local-https.md, smoke-test.md, M1…M4-REPORT.md, music-engine.md, architecture/
  data/             (gitignored) unheard.sqlite3, audio/, artifacts/, eval/
```

## Prerequisites

| Tool | Why | Verified version |
|---|---|---|
| [uv](https://docs.astral.sh/uv/) | Python 3.12 venv + locked deps (ADR-012; system 3.14 is not used) | 0.12.7 |
| Python 3.12 | installed automatically by `uv sync` | 3.12.13 |
| Node ≥ 20 + npm | frontend | Node 26.8.1 / npm 12 |
| **ffmpeg + ffprobe** | decoding browser codecs (webm/opus, mp4/aac, ogg, mp3). Without it only WAV/FLAC/OGG uploads decode (libsndfile fallback) and `/api/health` reports `ffmpeg_available: false` | 9.0.1 |
| mkcert (optional) | HTTPS on the LAN for phone testing, see [`docs/local-https.md`](docs/local-https.md) | — |
| torch + transformers (optional, `uv sync --extra ml`) | ECHO-0's ears (LAION-CLAP, ~600 MB weights, CPU) — see [`docs/model-setup.md`](docs/model-setup.md) | torch 2.14+cpu, transformers 4.x |

FFmpeg licensing: the project only *invokes* the `ffmpeg` binary found on `PATH` (LGPL/GPL
depending on your build); nothing from FFmpeg is linked or redistributed here. If `ffmpeg`
is missing, uploads in a container it cannot decode fail with `503 DECODER_UNAVAILABLE`.

## Setup

```bash
git clone https://github.com/miclaldogan/the-unheard && cd the-unheard
python3 scripts/verify_env.py          # prints python/ffmpeg/node status
(cd server && uv sync --extra ml)      # creates server/.venv with Python 3.12 (+ torch/transformers)
(cd server && uv run unheard fetch-model)   # one-time ~600 MB download of the CLAP weights
(cd web && npm install)
```

## Run

```bash
# terminal 1 — API on http://127.0.0.1:8000 (data in server/data/)
cd server && uv run unheard serve
# terminal 2 — UI on http://localhost:5173 (proxies /api to the backend)
cd web && npm run dev
```

Open <http://localhost:5173>. Interactive API docs: <http://127.0.0.1:8000/api/docs>.

Single-process mode: `cd web && npm run build` then `uv run unheard serve` serves `web/dist`
at `http://127.0.0.1:8000/`.

Configuration is via `UNHEARD_*` environment variables (see `server/unheard/config.py`):
`UNHEARD_DATA_DIR`, `UNHEARD_PORT`, `UNHEARD_API_TOKEN`, `UNHEARD_MAX_DURATION_S`, …

## Recording, hearing, teaching

1. Press **Record**, allow the microphone, press **Stop** (auto-stops at 30 s), listen to the
   preview, **Submit for analysis**.
2. The server validates and decodes the upload, extracts DSP features (`ready`), then queues
   inference: CLAP embeds the canonical audio in 10 s windows and scores every source label by
   cosine similarity to its text prompt. The **Hearing** panel shows the ranked hypotheses with
   their real score semantics (ears cosine, memory cosine, fused rank score) — never percentages.
3. ECHO-0 speaks only from persisted events: *"I hear something. My strongest hypothesis is …"*,
   *"I can hear it. I cannot name it yet."* when the novelty gate fires, *"This resembles
   something you taught me before"* when a remembered recording is close.
4. **Teach**: confirm or reject hypotheses, pick another known source, name a new one, or mark
   it unknown; optionally add descriptors (how it sounds), place and feeling — these three are
   stored separately and never used for recognition. Submitting stores the annotation and, if
   the recording has an embedding, one exemplar per source label in memory; previous
   annotations are superseded and their exemplars retracted; every other recording is
   re-scored and the response lists what changed.
5. **Acoustic memory** shows exemplar counts per name, learned names, memory version and the
   recordings most similar to the selected one. Deleting a recording removes its embeddings,
   predictions, annotations and exemplars and re-scores the rest.

Recordings made before M2 (or while the model was disabled) show *Not yet heard* with a
*Listen with ECHO-0's ears* button that queues inference.

6. **Specimen** (nav tab, or *Open visual memory*): the acoustic signature as the centrepiece —
   outline from the RMS envelope, fold symmetry from tonality, crispness from the centroid,
   gaps from spectral flux, one tick per onset, hue from the label. Play the original: the body
   breathes with the recorded envelope and onsets glow, synced to the audio position. Export
   PNG/SVG; toggle the waveform/spectrogram and numbers underneath.
7. **Atlas**: pan (drag), zoom (wheel), click a node for its relationships, filter by name or
   uncertainty, show your "feelings" as a separate subjective layer, open a specimen. The
   state line (first observation → emerging relationships → learned categories → new concept)
   is derived from real edges and anchors, not from counts.

### Supported formats and limits

Containers: WAV, WebM (opus/vorbis), MP4/M4A (aac), OGG, FLAC, MP3 — anything ffmpeg decodes
within those containers. Limits (configurable): 25 MiB, 3–30 s, source rate 8–192 kHz,
rejection below −60 dBFS RMS, clipping (> 0.5 % samples ≥ 0.99) flagged but accepted.

### DSP features (`dsp_version = 1`)

Computed on the canonical signal without gain changes; definitions with formulas are in
`server/unheard/dsp/features.py`. Scalar summary: duration, sample rate, peak/RMS (linear and
dBFS), clipping ratio, zero-crossing rate, spectral centroid / bandwidth / 85 % rolloff /
flatness / flux (mean, median, std, min, max over active frames; STFT 2048/512 Hann), onset
count and density (from a log-mel novelty curve), dominant mel band. Arrays (`.npz`): per-frame
series, RMS envelope, 64-band log-mel (25 ms / 10 ms), pooled STFT view, waveform buckets.
Same input + version ⇒ byte-identical output (tested).

## API

See [`docs/api.md`](docs/api.md). M1 endpoints unchanged; M2 adds `GET /api/model`,
`POST /api/model/load`, `GET /api/recordings/{id}/prediction`, `POST …/infer`,
`GET …/neighbours`, `GET/POST /api/labels`, `GET/POST …/annotations`, `GET /api/memory`,
`GET …/echo`. M3 adds `GET /api/recordings/{id}/visual`, `GET /api/atlas`,
`POST /api/atlas/rebuild`. Errors are RFC 7807 problem documents with stable codes.

## Tests

```bash
cd server && uv run pytest                      # fast suite (fake model), ~10 s
cd server && uv run pytest -m real_model -s     # real CLAP + ESC-50 integration test (needs weights + eval data)
cd server && uv run ruff check . && uv run mypy unheard
cd web && npm test && npm run typecheck && npm run build
cd server && uv run python ../scripts/bench_models.py   # model gate numbers
cd server && uv run python ../eval/run_eval.py          # before/after personalization (eval/README.md)
```

Manual browser checklist: [`docs/smoke-test.md`](docs/smoke-test.md).

## Current limitations

- No music, atlas or free narration (M3+). ECHO-0 lines are templates bound to events.
- Personal memory is retrieval only (kNN over CLAP embeddings); the model is never fine-tuned.
- Unknown detection is a thresholded heuristic measured on ESC-50 (`eval/reports`), not a
  calibrated detector; fused scores are rank scores, not probabilities.
- The specimen grammar is an artistic mapping of measured quantities, documented per
  parameter; the atlas is a 2-D PCA view of a 512-d space (explained variance shown in the UI).
- CPU inference only was measured; CUDA is possible but untested here.
- Phone capture over LAN HTTPS is wired but still untested on a physical phone; no offline queue.
- Hard delete (no tombstones); single worker; Linux + Chrome/Firefox only.

## Next milestone — M4

The symphony engine consumes what M1–M3 persist: canonical audio (`audio_asset`), DSP
summaries and arrays (`feature_set` + `.npz`: RMS envelope, onsets, centroid/flux series,
log-mel), embeddings and neighbours, confirmed/annotated sources, and the specimen's
precomputed animation timelines (`visual_artifact.params.animation`) for audio-visual sync.

License: MIT.
