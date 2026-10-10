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
| POST | `/api/recordings/{id}/annotations` | body below → `201 {annotation, memory_version, exemplars_added, exemplars_retracted, memory_pending, created_label_ids, rescored_changes, fused_top}`. `memory_pending: true` means the label is stored but the recording has no embedding yet, so memory has not changed; it is applied exactly once (event `AcousticMemoryUpdated` with `reason: annotation_backfill`) when inference completes. A later correction supersedes it, a deletion discards it. |
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

---

# M3 additions — specimens and the atlas

| Method | Path | Response |
|---|---|---|
| GET | `/api/recordings/{id}/visual` | `{artifact_id, recording_id, generator_version, seed, dsp_version, model_version_id, geometry_hash, status, params{geometry, animation, semantic}, created_at, updated_at}`; `409 NOT_READY` until DSP features exist. Created on first access if missing; refreshed when the semantic layer changes. |
| GET | `/api/atlas` | `{atlas_version, layout_version, generator_version, model_version_id, model, basis{fitted_on, frozen, explained_variance_2d}, nodes[], edges[], anchors[], state, counts, narrative[]}` — rebuilt from persisted artifacts/embeddings on every call (cheap), positions persisted. |
| POST | `/api/atlas/rebuild` | same shape; refits the PCA basis on all current nodes (explicit user action). |

`state` ∈ `empty · first_observation · scattered · emerging_relationships · learned_categories · new_concept`,
derived from real facts (edges exist, a label has ≥ 2 confirmed members, a user-created label
has members) — not from recording count.

Node fields: `recording_id, artifact_id, x, y, embedded, state, resolution, label, hue,
label_ids, confirmed_labels, is_unknown, descriptors, environment, mood, ears_top, fused_top,
novel, captured_at, duration_s, glyph{…}, ring[32], seed`. Edge fields: `a, b, type
(acoustic|shared_label), weight (cosine), label_id`.

Events: `ArtifactRendered` (per recording, when its specimen is created or its semantic layer
changes), `AtlasUpdated` (when nodes are placed or the basis is refit).

---

# M4 additions — compositions (the Orchestra)

A composition is a deterministic arrangement rendered offline from 1–8 ready recordings.
Rendering is asynchronous: `queued → processing → ready | failed`.

| Method | Path | Notes |
|---|---|---|
| POST | `/api/compositions` | body `{recording_ids[1..8], mode? ("composed" default | "organic" | "legacy"), seed?, controls?{density,structure,intensity ∈ 0..1}, duration_s? (15–90), role_overrides?{recording_id: role}, name?}` → `202` composition (`created: true`) or `200` with the existing one (`created: false`) when the same sources + seed + controls + duration + overrides + versions were already requested. `404` unknown recording, `409 NOT_READY` recording not ready, `422` bad input. |
| GET | `/api/compositions[?recording_id=]` | list items (`id, name, saved, status, seed, duration_s, tempo_bpm, n_sources, recording_ids`); the filter answers "which compositions use this specimen?" |
| GET | `/api/compositions/{id}` | full state: controls, tempo/key, `sections`, `sources[]` (label, role, secondary role, decision{scores, evidence, rationale, overridden}, analysis), `tracks[]` (role, pan, enters, `stem_url`, `original_url`), `metrics`, `echo[]` (conductor lines with evidence), `plan_hash`, `master_sha256`, `master_url`, `export_url`. |
| PATCH | `/api/compositions/{id}` | `{name?, saved?}` |
| DELETE | `/api/compositions/{id}` | removes rows and files (`204`) |
| POST | `/api/compositions/{id}/variation` | `{seed?, controls?}` → new composition (`parent_id` set); default seed derived from the parent |
| POST | `/api/compositions/{id}/render` | re-queues a `failed` composition (`409` if already running; no-op if ready) |
| GET | `/api/compositions/{id}/events` | the timeline: `seq, track_key, recording_id, kind (slice|loop|grains), role, section, comp_start_s, comp_dur_s, source_start_s, source_end_s, params{rate, gain_db, pitch_shift_st, octave_shift, lowpass_hz, highpass_hz, fade_*…}` |
| GET | `/api/compositions/{id}/trace/{seq}` | composition → track → event → source recording → specimen (`artifact_id`, `geometry_hash`), plus `also_in` |
| GET | `/api/compositions/{id}/master` | `audio/wav` (range requests supported); `409` until ready |
| GET | `/api/compositions/{id}/stems/{track_key}` | per-layer WAV; stems sum to the master |
| GET | `/api/compositions/{id}/export[?bundle=true]` | attachment: master WAV, or a zip with master, stems, `plan.json`, `provenance.json` |

Roles: `texture, drone, rhythmic_texture, percussion, tonal_motif, accent, granular`.
Deleting a recording (`DELETE /api/recordings/{id}`) also deletes every composition that
contains it. Events: `CompositionCreated`, `CompositionPlanned`, `CompositionRendered`,
`CompositionFailed`, `CompositionRevised` (variations), `CompositionDeleted` (`reason: user|source_deleted`).
Design and limits: [`music-engine.md`](music-engine.md).

---

# M4.6 additions — arrangement modes

`POST /api/compositions` accepts `mode`: **`composed`** (default; clear phrases, call-and-response, swing/ghost notes),
**`organic`** (source-timed, sparse, atmospheric) or **`legacy`** (the M4/M4.5 event planner, kept for comparison). The
mode is part of the idempotency key, so the same sources/seed in two modes are two compositions; variations inherit
their parent's mode. Invalid modes → `422`.

Composition responses gain: `mode`, `form` (phrase recipe per section, e.g. `"A + F F' Fa + R→A"`), `conversation[]`
(`{lead, responder, evidence{score, temporal_fit, spectral_contrast, tonal_consonance, pulse_relation}}`), `groove`
(`quantisation, swing_steps, micro_ms, ghost_notes, fills, tonal_strategy`), `hierarchy` (the chosen lead/foundation/
support/gesture/bed sources) and per-track `hierarchy` (`lead|foundation|support|gesture|bed`). List items gain `mode`.
Event `params` gain `hierarchy`, `motif`, `variation` (the operator-named variant, `response`, `fill`, `boundary` …),
`phrase`, `fragment`, `velocity`, `ghost`, and `pitch_shift_st`/`octave_shift`/`preserve_duration` for pitched notes; the
trace endpoint returns them unchanged. ECHO-0's `echo[]` adds an "answered in the silence" line, only when the plan
contains answer events, with the conversation evidence attached. Migration `0005` adds `composition.mode`.
