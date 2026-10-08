# THE UNHEARD

*An orchestra made of a world you almost forgot to hear.*

An open-source, local-first experience for the Hacktoberfest 2026 Open-Source AI Challenge
(Week 1, *Touch Grass*). You teach an amnesiac machine, ECHO-0, to hear by recording the real
world; its memory, atlas, artwork and music are built from your recordings.

## Status

**M1 — audio foundation: implemented.** A real microphone → upload → validation → decoding →
canonical PCM → DSP features → SQLite/files → API → browser visualisation pipeline works end
to end with real audio. See [`docs/M1-REPORT.md`](docs/M1-REPORT.md) for what was tested.

Not implemented yet (honestly): **no sound recognition, no learning, no music.** The
`inference` field in every API response is `not_run`. ECHO-0 only states what is true
("a signal has been preserved"). The audio model (CLAP / YAMNet) arrives in M2.

## Architecture summary

Modular monolith (docs/architecture/02): one FastAPI process with internal packages
`ingest → dsp → (models) → storage/events/jobs → api`, SQLite (WAL) + content-addressed
files under `data/`, and a Vite/React PWA. Processing is durability-first: the raw upload and
the recording row are committed before any processing; the DSP stage runs on an in-process
worker thread polling a `job` table; failures leave the recording inspectable and retryable.
Full design: [`docs/architecture/README.md`](docs/architecture/README.md).

```
the-unheard/
  server/unheard/   api/ ingest/ dsp/ models/ jobs/ events/ storage/  (+ app.py, cli.py, config.py)
  server/tests/     DSP, ingest, API, e2e tests + synthetic fixtures
  web/src/          api/ audio/ state/ components/  (React + TS)
  scripts/          mkcert.sh, verify_env.py
  docs/             api.md, local-https.md, smoke-test.md, M1-REPORT.md, architecture/
  data/             (gitignored) unheard.sqlite3, audio/, artifacts/
```

## Prerequisites

| Tool | Why | Verified version |
|---|---|---|
| [uv](https://docs.astral.sh/uv/) | Python 3.12 venv + locked deps (ADR-012; system 3.14 is not used) | 0.12.7 |
| Python 3.12 | installed automatically by `uv sync` | 3.12.13 |
| Node ≥ 20 + npm | frontend | Node 26.8.1 / npm 12 |
| **ffmpeg + ffprobe** | decoding browser codecs (webm/opus, mp4/aac, ogg, mp3). Without it only WAV/FLAC/OGG uploads decode (libsndfile fallback) and `/api/health` reports `ffmpeg_available: false` | 9.0.1 |
| mkcert (optional) | HTTPS on the LAN for phone testing, see [`docs/local-https.md`](docs/local-https.md) | — |

FFmpeg licensing: the project only *invokes* the `ffmpeg` binary found on `PATH` (LGPL/GPL
depending on your build); nothing from FFmpeg is linked or redistributed here. If `ffmpeg`
is missing, uploads in a container it cannot decode fail with `503 DECODER_UNAVAILABLE`.

## Setup

```bash
git clone https://github.com/miclaldogan/the-unheard && cd the-unheard
python3 scripts/verify_env.py          # prints python/ffmpeg/node status
(cd server && uv sync)                 # creates server/.venv with Python 3.12
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

## Recording and processing audio

1. Press **Record**, allow the microphone. Capture uses an `AudioWorklet` and produces 16-bit
   PCM WAV at the device's native rate (lossless); `MediaRecorder` (webm/opus or mp4/aac) is
   the fallback when AudioWorklet is unavailable. Constraints request
   `echoCancellation/noiseSuppression/autoGainControl = false`; whether the browser honoured
   them is stored in `device_info`.
2. Press **Stop** (auto-stops at 30 s). Listen to the preview; **Submit for analysis**.
3. The server sniffs the container from magic bytes (client MIME/extension are ignored),
   decodes with ffmpeg to 48 kHz mono float32, validates (3–30 s, not silent, ≤ 25 MB, NaN-free),
   stores the original bytes and the canonical WAV, commits the row, then the worker extracts
   features and writes `features_v1.npz`. The UI polls until `ready`.
4. **Analysis** shows the waveform (server-computed min/max/RMS buckets), the log-mel or STFT
   spectrogram (dB values from the server) and scalar measurements. Nothing is synthesised
   client-side.
5. **Archive** lists everything persisted; Play streams the original upload; Delete removes the
   row and every file for that id.

Upload from the command line:

```bash
curl -F "file=@clip.wav" http://127.0.0.1:8000/api/recordings
curl http://127.0.0.1:8000/api/recordings/<id>/features | jq .summary
```

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

See [`docs/api.md`](docs/api.md). Summary:

| Method | Path |
|---|---|
| GET | `/api/health` |
| POST | `/api/recordings` (multipart `file`, optional `captured_at`, `device_info`) → 202 |
| GET | `/api/recordings`, `/api/recordings/{id}` |
| GET | `/api/recordings/{id}/audio?variant=source\|canonical` |
| GET | `/api/recordings/{id}/features`, `/api/recordings/{id}/spectrogram?kind=mel\|stft` |
| POST | `/api/recordings/{id}/retry` |
| DELETE | `/api/recordings/{id}` → 204 |

Errors are RFC 7807 problem documents with stable codes (`AUDIO_TOO_SHORT`, `AUDIO_SILENT`,
`DUPLICATE_RECORDING`, …).

## Tests

```bash
cd server && uv run pytest            # DSP numerics, ingest, API, persistence, e2e
cd server && uv run ruff check . && uv run mypy unheard
cd web && npm test && npm run typecheck && npm run build
```

Manual browser checklist: [`docs/smoke-test.md`](docs/smoke-test.md).

## Current limitations

- No audio model, no predictions, no memory, no music, no atlas (M2+).
- Phone capture over LAN HTTPS is documented and wired (`scripts/mkcert.sh`, Vite TLS +
  proxy, bearer token) but **was not tested on a physical phone** in M1.
- No offline capture queue / service worker: the app is installable but needs the server.
- Deleting a recording hard-deletes it (doc 08's tombstone that blocks silent re-import is
  deferred to M2, when memory exemplars make it matter).
- One worker thread; one job at a time (by design, ADR-003).
- Only tested on Linux (Arch) with Chrome and Firefox.

## Next milestone — M2

Install and gate an open-weight audio model (CLAP primary / YAMNet fallback) behind the
`AudioModel` adapter in `server/unheard/models/contracts.py`, feed it the canonical PCM,
persist embeddings and predictions, add the annotation API and kNN memory so human labels
change later predictions. Only then will ECHO-0 be allowed to say "I heard".

License: MIT.
