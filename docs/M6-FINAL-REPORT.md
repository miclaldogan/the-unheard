# M6 final report: field validation, demo and submission preparation

Branch `feat/release-integration`, based on release candidate `1f4245d` (M5.5). Local commit only; nothing pushed,
merged or published. Deadline: October 11, 2026, 11:59 PM PDT.

## 1. Engineering status: READY, with human gates open

No new feature, framework, model or UI redesign was added. M6 fixed one real correctness bug, made phone testing possible
without extra tooling, and prepared the human validation and submission material.

| Area | Status |
|---|---|
| Learning race (teach before inference) | **Fixed and verified** (fake model, real CLAP, API, UI) |
| HTTPS for the production PWA | **Added** `--ssl-certfile/--ssl-keyfile`; verified on loopback with a self-signed certificate |
| Automated gates | **All pass** (section 6) |
| Real CLAP / real Gemma | **Pass** (section 4) |
| Physical Android | **NOT PERFORMED** |
| Human listening review | **PENDING** (tooling ready) |
| Gemma human rating | **PENDING** (sheet ready) |
| Demo video | **Not filmed** (script ready) |
| DEV article | **Draft**, owner-only passages marked, **not published** |

## 2. The learning race: what changed

**Problem (from the M5.5 report).** A name given before inference finished was stored but never became an acoustic exemplar;
resubmitting after inference was required, and the UI said a memory had formed.

**Fix (minimal, no schema change).**
* `MemoryService.backfill_pending` runs inside the inference transaction, right after the embedding is stored. It looks only at
  the recording's *active* annotation, skips unknown ones, skips an annotation that already has any exemplar (idempotency),
  inserts one exemplar per label, bumps the memory version, recomputes prototypes, rescored predictions and appends one
  `AcousticMemoryUpdated` event with `reason: annotation_backfill`.
* If the recording is deleted while inference runs, the result is dropped (`skipped: recording_deleted`).
* A crash inside the transaction rolls everything back; the annotation survives and a retry backfills exactly once.
* `POST /annotations` now returns an additive `memory_pending: true` while there is no embedding yet.
* The narrative evidence adds the fact "The name is stored, but the ears have not analysed this recording yet, so memory is
  not updated" for such annotations, so neither Gemma nor a template can claim learning that has not happened.
* The Hearing panel shows "memory has not changed" while pending and "A memory has taken shape" only when it did.

**Tests.** 10 new backend tests (`tests/test_learning_race.py`): pending flag; backfill once; retry and re-inference do not
duplicate; correction while pending learns only the latest label; unknown while pending adds none; deletion before
inference leaves no ghost memory; normal teaching is not pending; narrative fact present then absent; interrupted
inference rolls back and a retry learns once. 1 real-CLAP test: teaching two rain clips *before* inference, then inference,
then a re-run, gives exactly 2 exemplars and a held-out similarity of **0.837261**, identical to teaching afterwards. 1 frontend
regression test for the banner. 3 CLI tests for the TLS options.

## 3. HTTPS and the phone

`unheard serve --ssl-certfile F --ssl-keyfile F` (both or neither). Verified on loopback with a throwaway certificate: `/api/health`
over HTTPS; app shell, `manifest.webmanifest` and `sw.js` served; `/api/recordings` is 401 without the token and 200 with
it; plain HTTP to the TLS port fails; the bind address is unchanged. **Not verified:** mkcert (not installed here), binding to the
LAN address, the certificate on a phone. Procedure and results table: `ANDROID-FIELD-TEST.md`.

## 4. Real model integration status

| Check | Result |
|---|---|
| Real CLAP (laion/clap-htsat-unfused, CPU, offline cache) | 2 passed in 8.1 s (end-to-end learning test and the new pre-inference test) |
| Real Gemma (`gemma3:4b` via Ollama, production validator path) | 1 passed in 6.1 s |
| Live journey, disposable backend, real CLAP + Gemma | exit 0: 6 recordings, annotations, mission activation, a real 3-source Composed render (1.2 s), **ending reached**; held-out rain moved "Roof gutter" into rank 2, memory similarity 0.837261, 2 exemplars |
| Gemma statistics from that journey | 2 requests, 1 valid, 1 fallback (`invalid_json`). **Too few calls to be a rate.** |
| Scripted browser walkthrough (sandboxed Chrome 148, simulated microphone, production build) | passed, no page errors; 16 checks including offline capture and retry, annotation, specimen, Atlas, Organic and Composed compositions, mute/solo, seek, WAV export |

The scripted browser run is **not** a physical-device test; `physicalDevice: false` in its results.

Gemma figures from M5, restated exactly: 84.2% of 57 first attempts valid (reproduced on a second run), median warm latency
1.3 s, 3.3 GB model. The end-to-end fallback rate after the production retry was **not measured**. No Gemma fine-tuning exists.
CLAP, personalised kNN memory and Gemma narration are three separate mechanisms (see `HUMAN-REVIEW.md`, last section).

## 5. Human evaluation status

| Item | Status | Tool |
|---|---|---|
| Listening (Legacy/Organic/Composed x Natural/Urban/Hybrid) | **PENDING** | blind page `scripts/m6_listening_page.py`; nine excerpts matched to -20.0 LUFS; summary `scripts/m6_ratings.py listening-summary` |
| Gemma vs template, six criteria | **PENDING** | `eval/m6/gemma_human_rating.csv` (19 moments, blank), `m6_ratings.py gemma-summary` (prints PENDING until rated) |
| Automatic quality flags (not a human result) | Organic and Composed: none in 3 sets; Legacy: Urban (3 flags), Hybrid (1) | `server/data/m4_6/report.json` |

The summarisers print PENDING instead of numbers on empty input, and warn under 10 rated rows. No rating was fabricated; the only
synthetic fill used to test the arithmetic was written to a temporary copy and the real sheet was restored blank.

## 6. Test counts (final, on this tree)

| Gate | Result |
|---|---|
| Backend default suite | **283 passed**, 3 deselected (2 real-CLAP, 1 real-Gemma), 105.5 s |
| Real CLAP | 2 passed |
| Real Gemma | 1 passed |
| ruff format / ruff check / mypy (74 source files) | clean |
| Narrative schema export `--check` | exit 0 |
| Frontend | **78 passed** in 13 files; lint, typecheck, prettier clean |
| Production build | passes (main JS 263.3 kB, 84.3 kB gzip) |
| `npm audit --omit=dev` | 0 vulnerabilities |
| Live journey / browser walkthrough | pass (section 4) |
| New scripts lint/format | clean |

Baseline before M6 was 270 backend and 77 frontend tests; M6 added 13 backend (10 race, 3 CLI) plus 2 real-model gated, and 1 frontend.
Not run: a security scanner beyond `npm audit` and a pattern scan for secrets; Safari/Firefox; screen reader; large-library stress.

## 7. Documentation delivered

| File | Purpose |
|---|---|
| `docs/M6-FINAL-REPORT.md` | this report |
| `docs/ANDROID-FIELD-TEST.md` | phone setup, safe HTTPS, 20-step checklist, results table (blank) |
| `docs/HUMAN-REVIEW.md` | listening protocol and rubric, Gemma rating, what is and is not measured |
| `docs/DEMO-FINAL-SCRIPT.md` | ~110-second shot list, narration, on-screen text, music cues, edit rules |
| `docs/DEV-SUBMISSION.md` | article draft for DEV (not published) |
| `docs/FINAL-PUBLICATION-CHECKLIST.md` | repo audit, licences, claim guardrails, ordered owner actions |
| Updated | `README.md`, `docs/local-https.md`, `docs/api.md`, `docs/RELEASE-CHECKLIST.md` |
| Tools | `scripts/m6_listening_page.py`, `scripts/m6_ratings.py`, `eval/m6/gemma_human_rating.csv` |

## 8. Remaining release blockers

1. **The public repository does not yet contain the working project.** GitHub holds only the M5 backend branch and PR #1 (unmerged);
   the UI, integration and M6 work exist only locally. This must be resolved before submission, with your explicit approval.
2. The submission needs your own real passages (outdoor experience, teammate's DEV handle, video, screenshots).
3. A demo needs filming. Without a phone test, film the laptop and say so.

Not blockers but weaken claims: no Android test, no human listening, no Gemma human rating.

## 9. Readiness

| Question | Answer |
|---|---|
| Demo readiness | Software is ready to film; the recording itself is the owner's task |
| Publication readiness | **Not ready until the branch is pushed/merged and the article is finished** |
| Repository hygiene | Clean (no media, weights, databases, keys or local paths in tracked files) |
| Deadline | Oct 11, 2026, 11:59 PM PDT; today is Oct 10, 2026 |

## 10. Exact owner actions

See `FINAL-PUBLICATION-CHECKLIST.md` section E. In short, in order: Android test (45 min) -> listening review (25 min) -> optional
Gemma rating (20 min) -> record demo -> finish the article -> approve pushing/merging the release branch -> publish on DEV before
the deadline. If time runs short, prioritise a public working repo, an honest article and a truthful short demo.

## Limits worth stating publicly

Retrieval memory, not retraining. Gemma is a validated narrator, not the listener, and was not fine-tuned. Offline capture
only; no offline AI. Heuristic novelty. Musical quality unrated by humans. ESC-50 clips are private evaluation material.
