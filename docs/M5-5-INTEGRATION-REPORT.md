# M5.5 — integration and release-candidate report

## Release state and Git integration

Local engineering release candidate on **`feat/release-integration`**, worktree `../the-unheard-integration`.
The final fix/documentation commit is this branch’s HEAD, reported with its hash at delivery.
Nothing was pushed, merged into main, deployed, submitted or packaged as an APK.

Verified `c3040ce`, `923b4aa`, `3752cf7` and `490a584` locally; both branches descend from `c3040ce`.
All three original worktrees were clean before integration and remain unchanged.

| Merge | Parents | Result |
| --- | --- | --- |
| `13897b6` — complete M5 backend first | `c3040ce`, `3752cf7` | Preserves original contract `923b4aa` and implementation history |
| `679b718` — complete UI second | `13897b6`, `490a584` | Preserves UI implementation and its contract cherry-pick `437e0f2` |

No merge conflicts. The only changed-file collision was `docs/contracts/M5-NARRATIVE-API.md`; the two blobs
were identical and Git resolved it without editing. No implementation was overwritten and no existing commit
was cherry-picked again. Shared README/mobile setup documentation was updated only in this integration worktree.

## Contract and release fixes

Read contract `m5.1`, actual FastAPI/Pydantic schemas, React adapter and generation/service logic.
State, current utterance, mission list and activation request/response shapes match their actual responses.
Version checks, authentication, 404 compatibility fallback, abort/error handling, plain text, fact references,
line provenance and template/Gemma distinction were exercised. Settings, echo/history, model-status and
per-composition commentary are backend APIs; the UI does not offer separate settings/history/commentary screens.
The global composition/ending narrative is integrated. No progression logic was copied into React.

Fixes are limited to release integrity:

- Narrative snapshots belong to an explicit recording/data revision. A local delete/correction hides old narration
  immediately; aborted late reads cannot restore it. Composite keys avoid the collision between an incremented
  revision and decreased recording count. Two deferred-response tests cover this lifecycle.
- The persisted `remembered` phase shows the remembering instrument instead of an ongoing composing state.
- The provenance disclosure exposes actual fallback reasons, while the grounded line stays usable.
- Play stays disabled while authenticated stems load, preventing playback of a partly loaded composition.
  A deferred-load component test verifies loading and recovery.
- PWA shell cache advanced to v2; no forced activation during capture. Close all app tabs to activate a waiting update.
- Browser review’s direct API requests now carry the configured token, and its second composition explicitly clears
  previous choices before selecting three sources. Repeated input deduplication now enters the existing correction form instead of expecting an empty teaching form. A timed-out run overlapped a second QA profile mutation; the
  composition itself was ready. Sequential reruns with explicit selection passed. This was a review-harness issue.
- Model setup uses the actual environment name `UNHEARD_MODEL_NAME`, not the older documented `UNHEARD_MODEL`.
  HTTPS documentation removes insecure-context bypass advice and describes current PWA behavior honestly.

## Actual combined test results

These were executed on the integration checkout, not summed from prior milestone reports.

| Gate | Actual result |
| --- | --- |
| Final `server/.venv/bin/python -m pytest` | **270 passed, 2 deselected**, 111.36 s; local real-audio fixtures available, no skips |
| Earlier combined run before attaching audio fixtures | 266 passed, 4 skipped, 2 deselected; superseded by the final run above |
| Separate real CLAP smoke | **1 passed**, 6.01 s; six ESC-50 recordings, real CPU embeddings, held-out personalization |
| Separate real Gemma smoke | **1 passed**, 8.42 s through production Ollama/validator path |
| Frontend suite after fixes | **77 passed across 13 files**; includes 74 original UI tests plus 3 integration regressions |
| Python lint/format/types | Ruff clean, 104 server files formatted; strict mypy clean on 74 source files |
| QA script lint/format | `scripts/m55_real_journey.py` clean |
| API contract/schema verification | Included backend contract tests pass; `m5_export_schemas.py --check` passes |
| Frontend lint / TypeScript / formatting | Pass, zero lint warnings |
| Production build | Pass, Vite 7.3.7 |
| Dependency audit | 0 vulnerabilities |
| Real Chrome walkthrough | Pass; actual API/DSP/CLAP/Gemma, playback and export, no uncaught page errors |

Non-failing warnings: Starlette’s testclient/httpx deprecation and Node experimental localStorage notices.
The default backend suite uses model doubles in isolated tests; real-model smoke tests and the live combined
journey are separate evidence. The Gemma smoke permits validated fallback, but the live journey and pending
browser check additionally observed actual accepted Gemma output.

## Real player journey and model behavior

A fresh temporary database applied migrations 0001–0006. Empty prologue and actual laptop microphone capture
were checked separately from simulated-input automation. Local ESC-50 clips exercised real DSP and CPU CLAP,
annotation/correction, retrieval memory, measured specimens, real Atlas relationships and music rendering.
These evaluation clips stayed local and are not public demo assets.

Six distinct evaluation recordings (three rain, three church bells) produced 512-d CLAP embeddings. All three bells
had `church_bells` as base top-1 in the explicit smoke. Teaching two rain examples “Roof gutter” moved that name
into rank 2 on held-out rain; its nearest memory similarity was **0.837261** and it had two real exemplars.
The label was absent from the prior top three. This is retrieval/fusion, not retraining.

Annotations persisted. A backend-generated mission activated through the actual endpoint. A later actual mission
selection response used **Gemma**, `gemma3:4b`, with no fallback and evidence-bearing candidates.
A three-source, 24-second Composed request rendered a real composition and unlocked `act: ending`,
`phase: remembered` from persisted state. Source roles, plan facts and composition commentary were returned by
the backend. Reload retained progression. The browser also generated both modes and reached the ending.

The immediate composition narrative was a **pending template**; settled output was **ready Gemma** for the same
moment. A fresh browser profile captured pending template → accepted Gemma (7.676 s reported generation latency),
including reload during pending generation. No interaction was blocked by narration.

The recorded live-journey model-stat snapshot contained **8 requests: 7 valid, 1 fallback** (`invalid_output`).
Warm median was 1.751 s, observed cold-first 6.211 s, p95 7.676 s. These are a small QA sample from actual runtime
statistics, not an artistic-quality score or a general latency/fallback-rate guarantee. Later calls produced further
validator fallbacks; the deterministic line remained playable. No fabricated model response entered production.

## Browser, mobile and recovery evidence

Sandboxed **Chrome 148.0.7778.215**; sandbox protection remained enabled. Viewports: 1440×1000,
1366×900, 390×844 and 844×390. The full walkthrough used explicit simulated microphone input but actual
backend services. A separate browser context without a fake capture device recorded the **physical laptop
microphone** for about five seconds and uploaded it successfully. Microphone denial produced a visible `MIC_DENIED`
error and recovery controls. No physical phone, outdoor capture or human playback/listening is claimed.

Verified: prediction display and teaching, specimens/original playback, Atlas selection and zoom, Organic/Composed,
actual stem playback, seeking, mute/solo, WAV download, playback continuity into Atlas, reload and persistent progress.

Production PWA: normal persistent Chrome profile passed installability with no errors, reloaded the cached shell
offline, captured locally, reconnected and uploaded using bearer authentication. Original audio playback used an
authenticated blob URL. Cache inspection found shell assets/icons/manifest only: no `/api` or private audio. The initial
isolated PWA timing check used CLAP disabled; final authenticated browser/PWA reruns had real CLAP/Gemma available.
Physical Android HTTPS trust, installation UX, safe areas, sunlight/touch, lock behavior and microphone fidelity remain open.
No offline AI, guaranteed locked-screen/background capture, Background Sync or native APK is claimed.

Recovery was exercised with actual temporary services/data rather than mocked live game responses:

- Network loss: capture retained locally and manual retry succeeded.
- Lost response: actual server `202` committed the recording, then browser routing dropped the acknowledgement.
  Retry found the existing recording; count stayed **2**, instead of creating a third copy. Bytes remained local.
- CLAP unavailable: a deliberately missing local model produced `inference_failed`, while DSP-ready recordings/raw audio survived.
- Ollama unavailable: only our QA backend pointed at unreachable loopback port 9; the user’s Ollama service was untouched.
  Backend and browser showed a validated template with `fallback_reason: unavailable`.
- Failed render: only a disposable profile’s canonical asset was temporarily withheld; the render failed. Cleanup restored
  the file, `/render` retried successfully, and raw recordings remained accessible.
- Backend restart: the same QA database kept recordings/annotations; restoring actual CLAP made both predictions usable again.
  **Existing M2 limitation:** teaching before first successful inference preserves annotations but creates no acoustic exemplar.
  Resubmitting those labels after successful inference produced two exemplars. The UI does not automatically backfill them.

## Performance and resources

| Observation | Actual measurement |
| --- | --- |
| Main JS | 263.11 kB raw / 84.22 kB gzip |
| CSS | 32.41 kB raw / 8.08 kB gzip |
| CPU CLAP first load | 7.381 s, revision `8fa0f1c6d0433df6e97c127f64b2a1d6c0dcda8a` |
| Six 5-second CLAP inferences | 233.6–283.6 ms each |
| 24-second three-source Composed readiness | 1.217 s from request acknowledgement to ready, polling included |
| Production warm-reload DOMContentLoaded | 40.3 ms in the final PWA sample |
| JS heap at that reload | 3,987,737 bytes (~3.8 MiB) |
| Actual 5-node CLAP Atlas draw | 9.3 ms, existing single-draw instrument timer |
| Authenticated ~8.9 MB stem downloads | 10.7–13.5 ms on local loopback in a later sample |
| QA backend observed RSS | roughly 1.2–1.31 GB with loaded CLAP; observed samples, not a measured peak |
| Shared machine availability during model load | about 2.7 GB available at the lowest observed sample; swap in use |

One CPU CLAP backend and one Ollama Gemma model were used; explicit heavyweight smoke tests were sequential.
No unrelated applications were killed, and no OOM was observed. Shared RAM/swap pressure is real: keep one backend,
CPU threads bounded and avoid extra models. The frontend warm-load/Atlas samples are not cold-start, sustained FPS,
large-library, physical-phone, thermal or battery benchmarks. No listening-quality inference follows from these numbers.

## Screenshots, privacy and public-source audit

Current screenshots/metadata are indexed in [`integration-review/README.md`](integration-review/README.md).
They include prologue, physical microphone, Hearing, Specimen, Atlas, Orchestra, offline PWA, ending/provenance,
pending/settled Gemma and unavailable-runtime fallback. Earlier UI-only artifacts remain clearly separate.
The preserved reports contain ephemeral QA ids and real measurements, no audio or database.

Current tracked files/release artifacts and reachable Git history paths were scanned for audio, databases, weight files,
private keys and common credential patterns: **no forbidden file paths or likely credential matches**. This is a heuristic
source audit, not a formal security certification. No restricted clips, personal audio, model weights or test tokens were added.
Original icon rasterizations and original CSS/SVG remain the only visual assets; no third-party fonts or generated art.

Primary license references checked: [CLAP model card](https://huggingface.co/laion/clap-htsat-unfused)
(Apache-2.0 metadata), [Gemma Terms](https://ai.google.dev/gemma/terms), [ESC-50 repository](https://github.com/karolpiczak/ESC-50).
Individual evaluation-clip publication rights were not cleared. Twelve matched local A/B excerpts were prepared for listening
under `/tmp/unheard-m55-listening`, with no audio committed. `eval/m5/human_rating.csv` is preserved, unedited and unrated.

## Open gates and release readiness

Engineering integration is ready for owner review and a local demonstration. **Public release/competition demo approval
is pending** physical-phone/outdoor validation, human listening/prose review, consent/licensing for demonstration audio,
and owner screenshot/diff approval. Artistic/emotional verdicts remain unanswered in `RELEASE-CHECKLIST.md`.
The archive still requests the first 100 records; large-library and Safari/Firefox/screen-reader validation remain open.
Browser storage may be evicted; important originals should be downloaded. API authentication and trusted HTTPS remain
necessary when connecting a phone; there is no independently hosted cloud backend.

## Reproduce and integrate

Use README installation and model setup, then run backend/frontend gates above. For the real live-model journey:

```bash
# Terminal 1, from server/: new temporary profile, one backend and bounded CPU CLAP
UNHEARD_DATA_DIR=/tmp/unheard-m55-new-profile UNHEARD_TORCH_THREADS=2 \
  UNHEARD_NARRATIVE_MODEL=gemma3:4b uv run --extra ml unheard serve --port 8010
# Terminal 2, from server/: existing local evaluation clips, no publication permission implied
UNHEARD_REVIEW_URL=http://127.0.0.1:8010 \
  UNHEARD_ESC50_DIR=/absolute/path/to/local/esc50 \
  uv run --extra ml python ../scripts/m55_real_journey.py
```

Build the UI first for production browser tests. Provide Playwright Core and sandbox-capable Chrome through
`PLAYWRIGHT_MODULE` / `CHROME_PATH`; configure `UNHEARD_REVIEW_URL`, optional `UNHEARD_REVIEW_TOKEN`,
and `UNHEARD_REVIEW_DIR`, then run `web/scripts/browser-review.cjs` and `web/scripts/pwa-review.cjs` sequentially.
Use disposable profiles: the scripts mutate actual recordings/compositions. The private failure profile used temporary
asset withholding solely as fault injection; do not do that to a personal library.

Review the branch HEAD and merged history, then push **only with approval**. Integrate the complete branch after approval;
it already contains both implementations. Do not re-cherry-pick their commits or overwrite/reset either original worktree.
No push/main-merge approval is requested implicitly by this report.

### 🌐 Community Wisdom: [The Hidden Problems of Offline-First Sync](https://dev.to/salazarismo/the-hidden-problems-of-offline-first-sync-idempotency-retry-storms-and-dead-letters-1no8)
> **Source**: [Salazar](https://dev.to/salazarismo)
> **Tags**: `architecture`, `webdev`, `distributedsystems`, `nestjs`
>
> The article distinguishes retryable failures from terminal ones and stresses stable operation identity. Comments
> reinforced the oversized-payload retry trap and lost-response deduplication. This is one substantive source with
> supporting anecdotes, not a broad consensus claim. M5.5 tested those failure boundaries against the actual queue/backend.
>
> 🔗 [Read Full Discussion](https://dev.to/salazarismo/the-hidden-problems-of-offline-first-sync-idempotency-retry-storms-and-dead-letters-1no8)
