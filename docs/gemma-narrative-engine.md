# Gemma narrative engine (M5)

ECHO-0 is the voice of THE UNHEARD. In M5 it stops being a fixed script and becomes a *grounded, stateful narrator*
powered by a local Gemma model. This document describes how, and where the model is deliberately not trusted.

API shapes live in `contracts/M5-NARRATIVE-API.md`. Measured results live in `M5-REPORT.md`.

## 1. Three layers

```
 SQLite (recordings, annotations, predictions, compositions)
        │  pure function, no model
        ▼
 Layer 1  authoritative state      narrative/state.py  evidence.py  missions.py
        │  fact packet: F1…Fn with provenance      (the model never sees ids)
        ▼
 Layer 2  Gemma                    narrative/gemma.py  service.py
        │  JSON {lines:[{text, kind, cites:[F#]}]}
        ▼
 Layer 3  validator + fallback     narrative/validate.py  templates.py
        │  accepted lines, or the deterministic template line + a fallback reason
        ▼
 API / UI
```

* **Layer 1 decides what is true and what happens next**: the act, milestones, which mission is complete, which moment
  is current. Nothing here calls a model, so the story survives Gemma being absent, slow or wrong.
* **Layer 2 only words things.** It receives a short packet of facts and must answer in a JSON schema (enforced by
  Ollama's `format`), citing the facts it used by handle.
* **Layer 3 does not believe Layer 2.** Output that fails any check is discarded and a template line is served, with the
  reason recorded (`fallback_reason`).

## 2. What Gemma is used for

| Task | Input | Output | Authority |
|---|---|---|---|
| A. Memory interpretation | facts about a moment (first sound, teaching, correction, unknown, relationship) | 1–3 lines, 3–45 words each, grounded lines cite facts | wording only |
| B. Field missions | up to 4 backend-generated candidates | reordered / reworded objective text | cannot add missions, cannot judge completion |
| C. Dialogue and commentary | facts of a composition (sources, roles, tempo, answer pairs) | 1–3 lines of commentary | wording only |

A line is either `grounded` (cites ≥1 fact, may only use what those facts say) or `imagination` (cites nothing, no numbers,
no sound-source names). Imagination lines are labelled as such in the API so the UI can style them differently.

## 3. Evidence packet

Built by `evidence.facts_for`. Each fact: `handle`, `statement`, `provenance`, optional `ref`, and the `values`
(numbers and labels) the validator checks against.

Provenance vocabulary: `model` (the ears' hypothesis) · `user_confirmed` · `personal_memory` · `measurement` · `system` ·
`imagination`.

Example packet for a correction moment:

```
F1 [measurement]     The recording is 5 seconds long.
F2 [user_confirmed]  The player corrected the ears to 'Rain' for this recording.
F3 [model]           Before the correction the ears said 'Wind'.
F4 [system]          2 of the player's recordings are taught so far; 3 are needed to compose.
```

Never sent to the model: environment, mood, free-text notes, ids, file names, raw embeddings, audio. User-controlled
strings (label names, descriptors) are sanitized (NFKC, control/markup stripped, ≤ 48 chars), checked for
injection phrasing, and appear only inside single quotes in fact statements inside the `<facts>` fence.

## 4. Grounding rules (enforced, not requested)

The prompt asks for these; the validator guarantees them:

1. Every cite resolves to a handle in this packet (the model cannot name a recording, label or composition id).
2. Grounded lines have cites; every digit group or number word appears in a cited fact.
3. A quoted string must be a label/descriptor from a cited fact.
4. A sound-source noun (lexicon + the player's own label vocabulary) may appear only if a cited fact contains it.
5. No claims of visiting, seeing or being somewhere; no claims of retraining, learning-by-gradient or changing data.
6. No praise or motivational filler; no meta/prompt talk; no markup, URLs, UUIDs, handles (`F1`), or emoji.
7. 3–45 words per line, ≤ 3 lines, ≤ 90 words total.
8. Missions additionally may not mention places, GPS, night, strangers, approaching animals.

The "provenance" the UI shows is computed by the backend from the cited facts, never reported by the model.

## 5. Failure and fallback

| Situation | Behaviour | `fallback_reason` |
|---|---|---|
| Gemma disabled by setting or user | template, final | `disabled` |
| Ollama not running / no Gemma installed | template, final | `unavailable` / `no_model` |
| Call exceeds `narrative_timeout_s` (30 s) | template | `timeout` |
| Not JSON / schema mismatch | one retry, then template | `invalid_json` |
| Validator rejects | one retry with the rejection reasons, then template | `invalid_output` |
| Generation already running | template now, upgrade later | `busy` |

`GET /api/narrative/current` never waits for the model unless `wait_ms` (≤ 8000) is passed. It returns the template
line immediately (`generation.status: pending`) and a single background worker upgrades it. Results are cached by
`moment key + facts hash`, so repeated reads cost nothing and an edit (correction, deletion) changes the key.
Recording, classification, teaching and composition never call the narrator on their path.

## 6. State derivation and acts

`state.build_snapshot` reads the database and derives everything; there is no stored "story progress" to corrupt, and
existing users are reconstructed from their history on first read.

* **Prologue** (`awaiting_sound`): nothing recorded yet.
* **Act I – first hearing**: a recording exists; ends when the ears have analysed one recording (immediately, if the
  listening model is disabled).
* **Act II – teaching**: ends when at least 3 recordings carry a name from the player (confirm, correct, create).
* **Act III – the world remembered**: ends when a ready composition exists whose sources include at least 3 recordings the
  player has annotated.
* **Ending**: the above holds. Nothing depends on a particular label or on the ears having guessed right; "unknown"
  answers are recorded but do not count as names.

Milestones (first recording, first teaching, first correction, first unknown, first composition…) are derived the same way.

## 7. Missions

`missions.generate_candidates` proposes, from real gaps in the player's memory:
`record_first`, `resolve_unknown`, `gather_three`, `second_example` (a label with one example), `repeat_not_machine`
(all rhythmic taught sounds are mechanical), `find_tonal` (nothing taught has a pitch), `novel_sound`.

Each has a stable id (`msn_` + hash of type and key), a reason, evidence refs, an objective, a completion predicate and
a safe fallback sentence. At most 4 candidates, at most 2 active. **Completion is evaluated by the backend** from data
(new recordings after activation, annotations, onset density, voiced ratio, embedding similarity). Gemma can reword a
candidate; the validator ensures no place, danger or person-recording wording; nothing in the model output affects
completion. Every mission carries the fixed safety sentence: public paths, distance from animals, no recording people
without consent.

## 8. Model, runtime, license

| | |
|---|---|
| Default model | `gemma3:4b` (Ollama tag), 3.3 GB, fits a 4 GB GPU or CPU |
| Alternative | `gemma4:e4b-it-qat` (6.1 GB, thinking-capable; the engine sends `think:false`). Needs Ollama ≥ 0.30.5 and ~6 GB free |
| Runtime | Ollama HTTP API on `127.0.0.1:11434` (`/api/chat`, JSON-schema `format`, `keep_alive` 2 m, `num_ctx` 2048, `num_predict` 220). No other network access |
| Licenses | Gemma 3: Gemma Terms of Use. Gemma 4 e4b-it-qat: license text reads Apache 2.0 in the local Ollama manifest. Weights are never in the repo |
| Selection | `UNHEARD_NARRATIVE_MODEL` (empty = first installed of `narrative_model_preference`). The player can only switch Gemma on/off (`PATCH /api/narrative/settings`) |

Reproduce:

```bash
ollama pull gemma3:4b
cd server && uv run unheard serve                  # GET /api/narrative/model-status shows the selected model
uv run pytest -m real_gemma                        # real smoke test (needs Ollama)
uv run python ../scripts/m5_eval.py --models gemma3:4b --seeds 3 --out ../eval/m5
```

## 9. Limitations

* The model is small; it paraphrases within narrow facts and sometimes writes handles (`F1`) or odd phrasing. The validator
  rejects these and a template is served, so a share of moments show template text even with Gemma running.
* Grounding checks are lexical. They catch invented numbers, names, sources and ids; they cannot judge whether a sentence
  is *true in a deeper sense* or *good*. Prose quality is a human judgment (see the rating rubric in `M5-REPORT.md`).
* The sound-source lexicon is finite. A rare invented source noun absent from both lexicon and the player's labels would pass.
* The ears (CLAP) are a test double in this development environment; narrative behaviour with the real model is verified
  by the same code path but not by recorded fixtures here.
* ECHO-0 never retrains; the narrative says the ears' *memory* now holds a label, which is what personalised kNN does.
