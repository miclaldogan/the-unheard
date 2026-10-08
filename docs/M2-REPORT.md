# M2 Implementation Report — ECHO-0 hears, is taught, remembers

Date: 2026-10-09 · Branch: `feat/m2-echo-hearing` · Status: **PASS** (limitations listed at the end)

## Model selection

| | |
|---|---|
| Selected | **LAION-CLAP** `laion/clap-htsat-unfused`, revision `8fa0f1c6d0433df6e97c127f64b2a1d6c0dcda8a`, via `transformers` 4.x + `torch` 2.14.0+cpu |
| Licence | code Apache-2.0; weights listed Apache-2.0 on the Hub (training data mixed); downloaded by the user, never redistributed |
| Hardware verified | i7-13700H, 15 GiB RAM, **RTX 3050 Ti 4 GB** (doc 01 said RTX 4050 6 GB — corrected), Arch Linux, Python 3.12.13 |
| Load | 6.3 s cold (benchmark) / 2.5 s warm cache (server log) |
| RSS | 47 MB → 482 MB after load → 1082 MB peak over 184 clips |
| VRAM | 0 — CPU only. CUDA not installed (CPU latency already far under target; cu13 wheel set ≈ 3 GB) |
| Latency | cold 525 ms, warm p50 202 ms / p95 224 ms per 5 s clip; real 30 s mic recording (5 windows) 730 ms |
| Embedding | 512-d, L2-normalised |
| Zero-shot on 184 real ESC-50 clips, 39-label vocabulary | top-1 **0.728**, top-3 **0.897** (birds 1.00, bells 1.00, rain 0.91, footsteps 0.83, engine 0.33, wind 0.31) |
| Embedding quality | leave-one-out kNN recall@5 **0.978**; same-class cosine median 0.635, different-class median 0.161 |
| Rejected | YAMNet (TensorFlow dependency, closed vocabulary — no text prior for user names); PANNs/AST/BEATs (no text tower, same torch cost). None installed. |

Fixture set for the gate: ESC-50 subset (CC BY-NC 3.0, local use), 6 classes × 40 clips —
tonal (church bells), water-like (rain), bird-like (chirping birds), mechanical (engine),
mixed/transient (footsteps), low-energy/ambiguous (wind). Synthetic signals were used only in
unit tests with a fake model and are never reported as environmental audio.

## Implemented modules (server)

- `models/clap.py` — adapter: 10 s / 5 s-hop windowing, per-window and pooled embeddings,
  text-prompt embeddings, cosine scoring (max over windows), path-scrubbed errors.
- `models/manager.py` — lazy singleton with status `disabled|not_loaded|loading|ready|failed`,
  a lock serialising inference, no runtime downloads unless `UNHEARD_ALLOW_MODEL_DOWNLOAD=1`.
- `models/vocabulary.py` — 39 environmental source labels (slug / display name / prompt).
- `memory/engine.py` — kernel-kNN memory scores, log-linear fusion, novelty gate (pure NumPy).
- `memory/service.py` — label space, exemplars, prototypes, annotation lifecycle
  (supersede → retract → insert → bump version → recompute prototypes → re-score all → events).
- `jobs/inference.py` + `jobs/worker.py` — `infer` stage auto-queued after `dsp`; inference
  failure never changes the recording status (features stay usable) and is retryable.
- `storage/migrations/0002_inference_memory.sql`, `storage/repos_m2.py`, `storage/vectors.py`
  (float32 LE blobs, no pickle).
- `api/intelligence.py` + `api/schemas_m2.py` — 10 endpoints (docs/api.md).
- `cli.py fetch-model`, `scripts/bench_models.py`, `eval/run_eval.py`.

## Classification pipeline and score semantics

canonical 48 kHz mono → windows → CLAP audio embeddings → **base**: cosine(audio, "The
sound of …") per label, max over windows (`score_kind` = cosine similarity, not probability) →
**fused**: `s_base = softmax(cos / 0.05)` over the current label space (relative rank score),
`s_mem` from the 7 nearest exemplars with `exp(cos/0.07)` kernel mixed with a 10 % uniform
floor, `λ = n_rel/(n_rel+3)` where `n_rel` counts kNN exemplars with cosine ≥ 0.55,
`fused = softmax((1−λ)·log s_base + λ·log s_mem)`. Every candidate carries
`base_similarity`, `base_score`, `memory_similarity` (nearest exemplar cosine for that label),
`memory_score`, `n_exemplars`, `lambda`, `evidence ∈ ears|memory|both`. The UI shows cosines
and rank scores with bars; no percentages anywhere. Multi-label: the ranking is over
independent per-label cosines (max-over-windows gives presence semantics); the Teach panel
accepts several sources per recording; per-window top-3 are stored for temporal views.

**Deviation from doc 04 §3** (ADR-014): one global λ instead of per-class λ_c, because
a per-class λ can never let memory overrule a label with zero exemplars; mixing with a uniform
floor instead of absolute ε. Base cosines are recomputed from stored window embeddings against
the current label space, so names created after inference take part without re-running the model.

## Personalized learning — what an annotation changes

1. The previous active annotation (if any) is superseded and its exemplars retracted.
2. One exemplar `(pooled embedding, label)` per source label is inserted (only if the
   recording has an embedding for the current model version; descriptors/place/mood never
   create exemplars; `unknown` creates none).
3. `memory_version` increments; prototypes of touched labels are recomputed (unit mean,
   `n_eff`, spread σ).
4. Every recording with an embedding is re-scored (its own exemplars are excluded from its
   own kNN so it cannot vote for itself); the response and the `AcousticMemoryUpdated` event
   list which recordings' top label changed.
5. Events `AnnotationSubmitted`, `PredictionConfirmed|PredictionCorrected`,
   `CustomCategoryCreated`, `UnknownSoundObserved` are appended; ECHO-0 lines are rendered
   from them.

Exemplars from a different model revision are never mixed in (tested). Deleting a recording
cascades embeddings/predictions/annotations/exemplars, recomputes prototypes and re-scores.

## Data architecture (migration 0002)

`model_version`, `embedding` (window rows + pooled row `window_idx=-1`, float32 blob),
`label` (vocabulary|user, slug, text prompt + text embedding per model version),
`prediction` (`base` | `fused` with `memory_version`, `score_kind`, results/windows/novelty
JSON), `annotation` (active|superseded, `superseded_by`, labels, rejected, unknown,
descriptors, environment, mood, note, `prediction_id` = what the user saw), `exemplar`
(active|retracted, annotation × embedding × label), `prototype`, `memory_meta`. Foreign keys
with cascades; UUIDv7 ids. Tested: an M1 (schema 1) database with data upgrades in place; old
recordings stay complete and report `state: not_run` until `/infer` is called (explicit, no
silent reprocessing).

## API

`GET /api/model` · `POST /api/model/load` · `GET /api/recordings/{id}/prediction` ·
`POST /api/recordings/{id}/infer` · `GET /api/recordings/{id}/neighbours` · `GET/POST /api/labels` ·
`POST/GET /api/recordings/{id}/annotations` · `GET /api/memory` · `GET /api/recordings/{id}/echo`.
`RecordingDetail.inference` now reports the real adapter result (`status: ok`, model id,
revision, top cosines, embedding dim) or `not_run`. M1 endpoints unchanged.

## UI

Hearing panel (state chip Analyzing → Hypothesizing → Remembered, ranked table with ears /
memory / fused columns, unknown and disagreement notices, window details, retry) · Teach panel
(confirm/reject hypotheses, search known sources, name a new source, unknown, descriptors,
place, feeling; "Correct this" re-opens with history kept) · Acoustic memory panel (counts,
learned names with example links and prototype spread, similar recordings) · ECHO-0 log with
provenance tags (`model` / `memory`), every line bound to event ids.

## Evaluation (`eval/run_eval.py`, ESC-50 subset, split by fold = by source recording)

| exemplars/class | top-1 | top-3 | macro-F1 (6 cls) | mean rank of truth |
|---|---|---|---|---|
| 0 (base model) | 0.736 | 0.900 | 0.813 | 1.62 |
| 1 | 0.753 | 0.904 | 0.825 | 1.59 |
| 3 | 0.796 | 0.916 | 0.857 | 1.50 |
| 5 | **0.808** | **0.921** | **0.864** | 1.48 |

Per-class recall 0 → 5 exemplars: birds 0.97→0.97, bells 1.00→1.00, engine 0.36→0.68,
footsteps 0.82→0.94, rain 0.90→0.97, wind 0.35→0.35 (wind is never taught: it is the held-out
"unknown" class). 240 test decisions per setting × 3 seeds, 5 folds, no recording appears on
both sides. Fusion latency p50 < 1 ms.

Unknown handling: nearest-exemplar cosine separates the never-taught class from taught ones
with **AUROC 0.949**. The novelty gate (ADR-015: nearest < 0.55 AND (margin < 0.60 OR
entropy > 0.25)) flags **54 % of unknown-class clips at a 5 % false-flag rate**. Doc 04's
three-way AND never fired; thresholds are configuration, not guarantees.

Functional demonstration (real model, `tests/test_real_model.py`, passes): three church-bell
and three rain clips from distinct sources; teaching "Roof gutter" on two rain clips moved a
held-out rain clip's top-3 from `Rain, Fountain, Running water` to `Rain, Roof gutter,
Fountain` (nearest exemplar cosine 0.837) while bells stayed `church_bells`. With the fake
model the API test shows one example does not flip a ranking (λ = 0.25) and four do.

## Tests

| Suite | Result |
|---|---|
| `uv run pytest` (fast, fake model; M1 + M2) | **78 passed, 0 failed, 1 deselected** (the real-model test) in 9.8 s |
| `uv run pytest -m real_model` (real CLAP + ESC-50) | 1 passed |
| ruff / ruff format / mypy strict | clean |
| `npx vitest run` | 26 passed |
| `tsc`, `vite build` | clean |
| Browser smoke (Chrome, Linux, real mic): recording 1 → Hypothesizing (5 windows, 730 ms, "Ventilation hum" cosine 0.513 — a quiet room with a laptop fan) → novelty notice → confirm + descriptor → Remembered, memory v1; recording 2 (same room) → "This resembles something you taught me before: Ventilation hum", memory cosine 0.968, evidence `both`, λ=0.25; deleting recording 1 → 0 exemplars, memory v2, recording 2 re-scored with empty memory | ✅ |

## Performance

See "Model selection". The full `infer` stage for a 30 s recording (5 windows) took 0.73 s
on the CPU after a 2.5 s load; the worker handles one job at a time.

## Risks and limitations

- Thresholds (τ) were tuned on ESC-50, not on phone field recordings; expect more "unknown"
  outdoors with wind. They are env-configurable.
- CLAP is weak on engine/wind zero-shot (0.33 / 0.31); memory fixes engine (0.68 with 5
  examples) but cannot fix a never-taught class.
- Evaluation is 6 classes; a 39-label open vocabulary dilutes zero-shot scores (ESC-50 class
  names were mapped to the closest vocabulary label).
- `rescore_all` is O(recordings × exemplars); fine for hundreds, not thousands.
- The real field test (five outdoor recordings) was **not** run in this session; the
  laboratory checklist is in docs/smoke-test.md and the outdoor protocol in doc 11.
- GPU path untested. Phone LAN HTTPS still untested.

## Git

Branch `feat/m2-echo-hearing` from `e4da3c8` (M1). One commit; not pushed.

## M3 readiness

The atlas can consume now: `embedding` (pooled + windows, float32), `exemplar`/`annotation`
(label membership with history), `prototype` (centroids + spread), `feature_set` (DSP),
`/api/recordings/{id}/neighbours` (similarity), `captured_at` and window times, and the event
stream (`AudioInferenceCompleted`, `AcousticMemoryUpdated` with `rescored_changes`).
