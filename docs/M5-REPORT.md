# M5 report: ECHO-0 awakens

Branch `feat/m5-echo-awakens` (base `c3040ce`). Backend, docs and evaluation only; `web/` is untouched (owned by Codex).
Design: `gemma-narrative-engine.md`. API for the UI: `contracts/M5-NARRATIVE-API.md` (+ `M5-NARRATIVE-SCHEMAS.json`).

## What shipped

* A three-layer narrative: state derived from the database, Gemma over minimal fact packets, a strict validator with a
  deterministic template fallback. See the engine doc.
* Gemma does three jobs: grounded memory interpretation, rewording/ordering of backend-generated field missions, and
  commentary on compositions. It never chooses ids, decides completion or changes data.
* Progression (prologue → Act I → II → III → ending) derived entirely from persisted data, so existing users are
  reconstructed on first read. The ending needs a real composition from ≥ 3 annotated recordings, not specific labels.
* Seven mission types with deterministic candidates and completion (`record_first`, `resolve_unknown`, `gather_three`,
  `second_example`, `repeat_not_machine`, `find_tonal`, `novel_sound`).
* Versioned, additive API (`contract_version: m5.1`), migration `0006_narrative.sql` (schema version 5 → 6).
* Evaluation harness `scripts/m5_eval.py`, schema exporter `scripts/m5_export_schemas.py`.

## Measured results

Environment: Linux, 15 GB RAM shared with other apps, a 4 GB-class GPU, Ollama 0.30.7, `gemma3:4b` (3.3 GB, Gemma Terms
of Use). The listening model (CLAP) weights are not installed here, so the "ears" are the project's deterministic test
double; the audio is real ESC-50 clips through the real ingest/DSP/music pipeline (local only, not committed).

Evaluation journey: 19 narrative moments reaching the ending, 3 seeds per moment for Gemma = 57 real model calls.
Command: `cd server && uv run python ../scripts/m5_eval.py --models gemma3:4b --seeds 3 --out ../eval/m5`.

| Metric | Result |
|---|---|
| Template-only: valid under the validator | 19/19 (100%) |
| Gemma, first attempt valid | 84.2% (48/57), reproduced on two consecutive runs |
| Gemma, JSON/schema compliant | 100% (Ollama schema-constrained decoding) |
| Gemma, invalid references | 0% (the model cannot emit ids) |
| Gemma, first attempt rejected | 15.8%; remaining reasons: handle written into prose (`F1`), numbers or quoted labels not in the cited facts |
| Latency, warm | p50 1.30 s, p95 1.89 s, mean 1.40 s |
| Latency, cold model load | 1.0–14.1 s across runs (file cache dependent) |
| Memory while running | Ollama ≈ 1.96 GB RSS, ≈ 2.78 GB GPU; Python process peak ≈ 480 MB |
| Wording diversity (distinct-1 / distinct-2) | Gemma 0.20 / 0.48, templates 0.29 / 0.63 |
| Same moment, different seeds: wording variety | 0.93 |

How to read this:

* The first-attempt rejection rate is the validator doing its job, not a bug count. In production a rejected attempt is
  retried once with the rejection reasons, then the template is served. The harness measures first attempts only; I did
  **not** measure the post-retry fallback rate end to end, so I make no number claim for it. If failures were independent
  the residual would be about 2.5% (0.158²), but that is an assumption, not a measurement.
* The distinct-n numbers are lower for Gemma than for templates, so Gemma is not "more varied" per word; its advantage is
  that the same moment is phrased differently each time (0.93) and it adapts to the facts at hand.
* **No claim that Gemma makes the story better.** Metrics here check grounding, schema, policy and latency only. Whether
  the prose is better is a human judgement; the blind A/B sheet is `eval/m5/human_rating.csv` and **no human has rated it
  yet**. Rubric (1–5 each): *relevance* (uses what actually happened), *clarity*, *character* (curious, precise, uncertain,
  never cheerful), *creativity*; plus an overall preference. Option order is shuffled; the key is in the last column.
* An earlier first-attempt rate of 71.9% came from a validator bug (a possessive apostrophe, as in "the ears' strongest
  hypothesis", was parsed as an opening quote). Fixing it, with a regression test, produced the 84.2%. A prompt tweak that
  told the model not to write handles in prose *increased* handle leaks (14 vs 9) and was reverted.
* `gemma4:e4b-it-qat` (6.1 GB) is installed but was **not evaluated**: free memory was about 6 GB on a shared machine, so
  I did not load it. No numbers are claimed for it.

Condition C (Gemma unavailable, timeout, invalid output): every one of the 19 moments is served a valid template with
a recorded `fallback_reason`; verified in the harness and in API tests.

## Tests

`cd server && uv run pytest` → **266 passed, 4 skipped, 2 deselected** (deselected: the slow `real_model` and `real_gemma`
suites). `ruff format --check`, `ruff check` and `mypy unheard` are clean.

New in M5: 39 validation/injection tests, 38 API/behaviour tests, 9 contract-sync tests, plus a real Gemma smoke test:
`uv run pytest -m real_gemma` (needs Ollama; run and passing here against `gemma3:4b` through the production path).

Covered: progression and gates, existing-user reconstruction, corrections/deletion/unknown, mission generation and
completion, provenance, hallucinated numbers/labels/sources, invented ids, prompt-injection labels, timeouts, invalid
JSON, unavailable model, concurrency (ten parallel reads → one generation), caching, API compatibility with earlier
milestones. Two existing tests that hard-coded schema version 5 were updated to 6 (and the in-place M1 upgrade test now
also hides migration 0006).

Not covered: browser/UI behaviour (Codex), the real CLAP model, human rating of the prose.

## Limits and risks

* Prose quality with a 4B model is unproven; lexical grounding cannot judge meaning (engine doc §9).
* A fixed sound-source lexicon bounds the "invented source" check.
* The first Gemma call after idle pays the model-load cost; the template is shown meanwhile.
* Cold-load and VRAM figures come from one machine.

## Integration for Codex

Read `contracts/M5-NARRATIVE-API.md`. Poll `GET /api/narrative/current` after any recording, annotation or composition
event; render `lines` immediately and replace them when `generation.status` goes from `pending` to `ready`. Show
`provenance` per line. Use `PATCH /api/narrative/settings` for the Gemma toggle. Never ask the backend to say the ears
were "retrained". A scoped README addition is prepared in `docs/M5-README-PATCH.md` and is intentionally not applied.
