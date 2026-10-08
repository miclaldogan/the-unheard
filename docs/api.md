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

---

# M2 additions — hearing, teaching, memory

All under `/api`, same auth and error rules. Score semantics are stated in every response
(`score_kind`); **no value is a calibrated probability**.

| Method | Path | Response |
|---|---|---|
| GET | `/api/model` | `{status: disabled\|not_loaded\|loading\|ready\|failed, model_id, revision, device, embedding_dim, preprocessing_version, load_seconds, error, inference:"local", known_versions}` |
| POST | `/api/model/load` | loads the model now (otherwise lazy on first job); `409 NOT_READY` if disabled/failed |
| GET | `/api/recordings/{id}/prediction` | `{state, model_status, model, job, base, fused, annotation}` — see below |
| POST | `/api/recordings/{id}/infer` | `202` queues the `infer` job (old recordings, retries); `409` if not `ready` or already queued |
| GET | `/api/recordings/{id}/neighbours?limit=5` | most similar other recordings by pooled-embedding cosine, with their labels |
| GET | `/api/labels?q=` | source labels (vocabulary + user) with exemplar counts |
| POST | `/api/labels` `{name}` | `201` creates (or returns the existing) user label; slug-normalised, 1–48 chars |
| POST | `/api/recordings/{id}/annotations` | body below → `201 {annotation, memory_version, exemplars_added, exemplars_retracted, created_label_ids, rescored_changes, fused_top}` |
| GET | `/api/recordings/{id}/annotations` | history, newest first (`status: active\|superseded`, `superseded_by`) |
| GET | `/api/memory` | `{memory_version, exemplars, annotations, unknown_annotations, custom_labels, labels:[{name, origin, n_exemplars, recording_ids, prototype{n_eff,sigma}}]}` |
| GET | `/api/recordings/{id}/echo` | ECHO-0 lines `[{template, text, tags:[model\|memory\|imagination], event_ids}]`, each derived from persisted events |

## Prediction states

`model_disabled` · `not_run` (no inference yet, e.g. M1 recordings — call `/infer`) ·
`analyzing` (job queued/running) · `inference_failed` (job failed; features intact; `/infer`
retries) · `awaiting_feedback` (hypotheses exist, no annotation) · `remembered` (annotated).

## `base` vs `fused`

- `base.candidates[]`: `{label_id, slug, name, rank, similarity}` — **cosine similarity** between
  the CLAP audio embedding and the label's text prompt, max over 10 s windows. Ears only.
  `base.windows[]` keeps the top-3 per window for temporal views.
- `fused.candidates[]`: `{rank, fused_score, base_similarity, base_score, memory_similarity,
  memory_score, n_exemplars, lambda, evidence}` at `fused.memory_version`.
  `fused_score` is a relative ranking score over the current label space (sums to 1),
  `memory_similarity` the nearest exemplar cosine for that label, `evidence` ∈ ears|memory|both.
- `fused.novelty`: `{novel, nearest_exemplar_similarity, fused_margin, base_entropy_normalised,
  memory_size, relevant_exemplars, lambda, nothing_similar_remembered, disagreement, ears_top,
  memory_top, neighbours[], thresholds}`.

## Annotation body

```json
{"label_ids": ["<label uuid>", "..."], "new_labels": ["Roof gutter"], "rejected_label_ids": [],
 "is_unknown": false, "descriptors": ["continuous", "soft"], "environment": "park", "mood": "calm", "note": null}
```
Limits: ≤ 6 source labels, ≤ 3 new names (1–48 chars), ≤ 10 descriptors (≤ 32 chars),
environment/mood ≤ 80 chars, note ≤ 500. `is_unknown` clears source labels. Only source labels
feed memory; descriptors/environment/mood are stored on the annotation and never used for
recognition. A new submission supersedes the previous one and retracts its exemplars.

## Events (append-only `event` table)

`AudioInferenceCompleted`, `AudioInferenceFailed`, `AnnotationSubmitted`,
`PredictionConfirmed`, `PredictionCorrected`, `CustomCategoryCreated`,
`AcousticMemoryUpdated` (with `rescored_changes`), `UnknownSoundObserved` (`by: system|user`).
