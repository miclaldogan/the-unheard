# THE UNHEARD — frontend delivery report

## Status and isolation

P0 is implemented and verified. P1 offline capture, installable PWA, restrained motion, real M5 progression, browser screenshots and basic performance measurements are implemented. Native packaging and physical-phone validation remain outside this delivery.

Worktree: `../the-unheard-ui`. Branch: `feat/ui-cinematic-experience`. Baseline verified locally: `c3040ce`. The branch first cherry-picked Claude's contract commit `923b4aa` as `437e0f2`; the final frontend commit is the branch HEAD reported at delivery. No `server/**`, root README, models, credentials, user recordings or database files were changed or committed. Nothing was pushed or merged.

## Completed experience

Chamber, mobile Field Ready/Recording/Saved/Notebook, Hearing, Specimen, Atlas and Orchestra all use the real backend. An engraved observatory design system uses graphite/ivory, readable copper/teal accents, editorial system-serif titles, sans-serif interaction text and monospace measurements. First use is a short actionable invitation; returning users see their actual memories and M5 progression.

Meaningful interactions include durable save before upload, explicit sync state, quick field notes, annotation-success memory formation, specimen awakening from measured audio, accessible atlas selection/zoom/pan, persistent orchestra playback, shared audible focus, source comparison, volume, mute/solo and exports. Navigation cannot hide active capture. Reduced motion and safe-area layouts are provided.

New components: `Chamber`, `EchoCore`, `FieldCollection`, `FieldMission`, `NarrativeVoice`, `ProtectedDownload`. Modified components: `RecordingPanel`, `HearingPanel`, `Archive`, `Specimen`, `Atlas`, `Orchestra`, plus `App`. Existing analysis, prediction, teaching, memory and signature renderers remain functional. `platform/` provides durable capture, upload recovery, device/lifecycle boundaries, audible focus and authenticated-original loading.

## M1–M5 integration

M1 capture, processing, waveform/spectrogram and quality measurements are preserved. M2 hypotheses, score semantics, annotations, corrections and memory retrieval remain on their existing endpoints. M3 deterministic specimen geometry and stable graph layout are unchanged. M4/M4.6 event plans, Organic/Composed generation, playback, traces, source comparisons and exports remain authoritative.

M5 uses the committed `m5.1` API contract: state, current utterance, missions and activation. Plain-text grounded/imagination lines expose provenance and facts. Pending narration polls without blocking recording. Backend absence, error and contract-version mismatch have explicit fallback behavior. The integration was exercised against Claude's real, still-in-progress M5 worktree; no backend code was copied into the UI branch. Actual responses reached `act: ending`, `phase: remembered` after annotations and a ready three-source composition. A mission was activated through the actual backend. CLAP/Gemma were disabled in this isolated browser run, so it validates DSP and template-based narrative integration, not their model quality.

## Mobile and PWA behavior

The production shell reloaded offline in Chrome and captured audio while disconnected. Its manifest and raster icons passed Chrome's installability check in a normal persistent profile. Cache inspection found only HTML/assets/icons/manifest, with no API/audio entries. Authenticated upload and specimen playback passed against a token-protected test backend.

IndexedDB saves stable local UUIDs, timestamps, metadata and original bytes. Bounds are 64 MiB / 100 recordings; storage errors preserve a downloadable in-memory preview. Local copies survive failed upload and remain after synchronization until user deletion. Explicit upload intent enables bounded foreground retry after reconnect/reopen; duplicate acknowledgements reuse backend IDs. A real IndexedDB check rejected the 101st capture without eviction and recovered after deleting one. There is no offline AI or guaranteed background recording.

## Verification and performance

| Check | Actual result |
| --- | --- |
| Frontend unit/component suite | 74 passing tests across 12 files; all 57 baseline tests retained |
| Strict TypeScript | Pass |
| ESLint incl. hooks / zero warnings | Pass |
| Prettier check for new UI/adapters | Pass |
| Production build | Pass, Vite 7.3.7 |
| Dependency audit | 0 vulnerabilities after updating inherited development tools |
| Main JavaScript | 262.65 kB raw / 84.10 kB gzip |
| Stylesheet | 32.41 kB raw / 8.08 kB gzip |
| Production warm-reload DOMContentLoaded | 66.3 ms on local desktop Chrome in the PWA run |
| JS heap at that reload | ~4.0 MiB |
| Atlas draw | 3.7 ms reported by existing instrument timer, four real nodes, model disabled |
| Portrait/landscape overflow | 390/390 px and 844/844 px viewport/document width |
| Browser interaction/runtime | Walkthrough passed, no uncaught page errors |

The bundle contains no new runtime dependency or external font request. Existing canvas batching/deterministic rendering is preserved. These figures are local observations, not cold-load, large-library, 60-fps, physical-phone or battery guarantees. Tests can still emit baseline React `act`/Node experimental-localStorage warnings; they pass without unhandled errors. Playback test timers were explicitly disposed to remove a baseline teardown leak.

Browsers/viewports: sandboxed Chrome 148 at 1440 × 1000, 1366 × 900, 390 × 844 and 844 × 390. Microphone input was simulated by Chrome, while upload, processing, annotations and composition generation were real API interactions. No physical Android/iPhone, Safari or Firefox validation was performed.

## Review, provenance and remaining work

Screenshots and machine-readable results are committed under `docs/ui-review/`; its README is the visual index. The manual/browser/mobile/artistic protocol is `docs/UI-MANUAL-TEST-CHECKLIST.md`. Assets are original CSS/SVG plus raster sizes of the existing repository icon. No AI-generated bitmap art or redistributed fonts were used.

The laptop remains the analysis/composition backend; secure reachable HTTPS and the existing optional bearer authentication must be configured for phones. Actual Android installation, sunlight readability, microphone fidelity, suspension, screen reader behavior, Safari/Firefox and long-library stress tests remain human/device checks. Native adapters are planned but no APK is supplied. The archive still uses the first 100 API records. No narrative-history/settings screen or dedicated per-composition M5 commentary UI was added. Browser storage may be evicted/cleared; important originals should be downloaded. The worker cache version must be advanced when changing shell releases; updates are not forced during capture.

## Final integration

1. Review the screenshots and diff, then run the physical-phone checklist.
2. Integrate Claude's completed backend on its own branch. The contract already exists there; do not apply it twice.
3. After approval, cherry-pick the final **frontend implementation commit** from `feat/ui-cinematic-experience` onto the intended integration branch. Do not merge/reset the original worktree concurrently with Claude.
4. Use Node 22.13+ (22.x) or 24+, then `cd web && npm ci && npm run lint && npm run typecheck && npm test && npm run build`.
5. Serve `web/dist` and `/api` through the same trusted origin. In Vite development, configure `UNHEARD_BACKEND` rather than building in a LAN IP. Follow `docs/local-https.md` for phone access and authentication.
6. Repeat the browser scripts and human checklist against the final combined backend. Update the root README during final integration only. Pushing, merging, deployment and APK packaging require separate approval.

Browser tooling: install/provide Playwright Core and a sandbox-capable Chrome executable; set `PLAYWRIGHT_MODULE`, `CHROME_PATH`, `UNHEARD_REVIEW_URL`, optionally `UNHEARD_REVIEW_TOKEN`, and `UNHEARD_REVIEW_DIR`. Run `node web/scripts/browser-review.cjs` against a disposable M5 backend and `node web/scripts/pwa-review.cjs` against a production build. The scripts deliberately create test captures and compositions, so never point them at a personal recording library. For a full three-source ending walkthrough, supply three taught recordings or run the collection flow repeatedly. Outputs default to `/tmp`; microphone simulation is explicit in the reports.

### 🌐 Community Wisdom: [Offline Queue Replay and Idempotency in Offline-First PWAs](https://dev.to/crisiscoresystems/offline-queue-replay-and-idempotency-in-offline-first-pwas-3hpg)
> **Source**: [CrisisCore Systems](https://dev.to/crisiscoresystems)
> **Tags**: `architecture`, `frontend`, `javascript`, `webdev`
>
> The article argues for stable operation identity and truthful queued/synchronized states. No comments were returned. This informed preserving original bytes and capture time, reusing acknowledged server IDs, and recovering lost responses through the existing backend's deduplication. A second inspected article emphasized separating permanent failures from retries; this is a small evidence base, not a broad consensus claim.
>
> 🔗 [Read Full Discussion](https://dev.to/crisiscoresystems/offline-queue-replay-and-idempotency-in-offline-first-pwas-3hpg)
