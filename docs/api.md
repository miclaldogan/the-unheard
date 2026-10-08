# API contract (v1, M1)

Base path `/api` (doc 08). All errors are RFC 7807 `application/problem+json` with a stable
`code`. Interactive docs: `/api/docs` (OpenAPI at `/api/openapi.json`).

Authentication: none by default (loopback). When the server runs with `UNHEARD_API_TOKEN`
(mandatory for `--lan`), every route except `/api/health` requires
`Authorization: Bearer <token>` → `401 UNAUTHORIZED` otherwise.

## Processing states

`uploaded → processing → ready` or `failed`. The upload response is `202 Accepted`; the client
polls `GET /api/recordings/{id}` until `status` is `ready` or `failed`. A failed recording keeps
its raw audio and can be re-queued with `POST …/retry`.

## Endpoints

| Method | Path | Request | Response |
|---|---|---|---|
| GET | `/api/health` | — | `200` `{status, version, api_version, dsp_version, schema_version, inference:"local", model_loaded:false, decoder{ffmpeg_available,…}, limits{…}, recordings, free_disk_bytes, python}` |
| POST | `/api/recordings` | multipart: `file` (audio), optional `captured_at` (ISO-8601), `device_info` (JSON object string) | `202` `{recording_id, status:"uploaded", duration_s, quality, links}` |
| GET | `/api/recordings?limit=&offset=` | — | `200` `{items:[RecordingSummary], total, limit, offset}` |
| GET | `/api/recordings/{id}` | — | `200` `RecordingDetail` (summary + `assets`, `jobs`, `features` summary or `null`, `inference`, `links`) |
| GET | `/api/recordings/{id}/audio?variant=source|canonical` | — | `200` the original upload bytes (default) or the canonical 48 kHz mono float32 WAV |
| GET | `/api/recordings/{id}/features` | — | `200` `{dsp_version, artifact_sha256, summary, waveform{min,max,rms}, series{times_s, rms_envelope_db, centroid_hz, bandwidth_hz, rolloff_hz, flatness, flux}, onset_strength, onset_times_s}` · `409 NOT_READY` before processing |
| GET | `/api/recordings/{id}/spectrogram?kind=mel|stft&max_frames=1024` | — | `200` `{kind, n_bins, n_frames, frames_pooled, freqs_hz, times_s, min_db, max_db, values[n_bins][n_frames]}` (dB) |
| POST | `/api/recordings/{id}/retry` | — | `202` re-queues the DSP job; `409 NOT_READY` if one is already queued/running |
| DELETE | `/api/recordings/{id}` | — | `204`; removes the row (cascading assets, features, jobs) and every file under `data/audio/…/{id}` and `data/artifacts/…/{id}` |

`inference` in `RecordingDetail` is the model-adapter contract. In M1 it is always
`{"status":"not_run","model_id":null,"model_version":null,"predictions":[],"embedding":null,"error":null}`.
Production code never emits predictions until a real model adapter exists (M2).

## Error codes

| HTTP | code | when |
|---|---|---|
| 401 | `UNAUTHORIZED` | token configured and missing/wrong |
| 404 | `NOT_FOUND` | unknown or malformed id (ids are UUIDv7; anything else is 404, never a path) |
| 409 | `DUPLICATE_RECORDING` | identical canonical PCM already stored; body carries `recording_id` |
| 409 | `NOT_READY` | features requested before processing finished / retry while a job is active |
| 413 | `AUDIO_TOO_LARGE` | upload > 25 MB |
| 415 | `AUDIO_UNSUPPORTED_FORMAT` | magic bytes not wav/webm/mp4/ogg/flac/mp3 |
| 422 | `AUDIO_EMPTY`, `AUDIO_UNDECODABLE`, `AUDIO_TOO_SHORT` (< 3 s), `AUDIO_TOO_LONG` (> 30 s), `AUDIO_SILENT` (RMS < −60 dBFS), `AUDIO_BAD_SAMPLE_RATE` (outside 8–192 kHz), `AUDIO_INVALID_SAMPLES` (> 1 % NaN/Inf) | ingest rejection; nothing is stored |
| 422 | `VALIDATION_FAILED` | malformed request (missing file, bad `device_info`) |
| 503 | `DECODER_UNAVAILABLE` | ffmpeg missing and the container is not wav/flac/ogg |
| 500 | `INTERNAL_ERROR` | unexpected |

## Limits (configurable via `UNHEARD_*` env vars)

| limit | default |
|---|---|
| upload size | 25 MiB |
| duration | 3 s – 30 s |
| source sample rate | 8 kHz – 192 kHz |
| canonical rate | 48 kHz mono float32 |
| silence rejection | RMS < −60 dBFS |
| clipping flag | > 0.5 % of samples with \|x\| ≥ 0.99 (flagged, not rejected) |
