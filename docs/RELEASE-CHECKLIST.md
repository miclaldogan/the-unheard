# Release checklist (M5.5, updated in M6)

This is a local release candidate, not publication approval. See the integration report for measured evidence.

## Engineering gates completed

- [x] Baseline `c3040ce`, source commits, ancestry, clean original worktrees and file overlap verified.
- [x] Complete backend then UI branches merged with history preserved; no conflicts or duplicate cherry-picks.
- [x] Combined backend/frontend suites, lint, types, build and narrative schema synchronization pass.
- [x] Real CPU CLAP and local `gemma3:4b` smoke tests pass separately.
- [x] Real classification → annotation → retrieval learning → specimen/Atlas → three-source composition → ending.
- [x] Sandboxed Chrome: hardware laptop recording; permission denial; all six scenes; both musical modes;
  mute/solo, seek, navigation during playback, original playback, export and persisted progress.
- [x] Real template → Gemma replacement observed in the browser, including reload during pending generation.
- [x] Unavailable model/runtime fallback, failed render/retry, backend restart and lost upload acknowledgement checked.
- [x] Authenticated production PWA: installability, offline reload/capture, synchronization, no private API/audio cached.
- [x] Current tracked tree and reachable history audited for private audio, databases, weights and likely secrets.
- [x] Existing original worktrees preserved; no push, main merge, deployment or APK.

## M6 additions

- [x] Learning race fixed: a name given before inference becomes exactly one exemplar when inference completes; verified with
  the fake model (9 tests) and with real CLAP (same 0.837261 held-out similarity as teaching afterwards). The UI no longer says
  memory formed while it is pending (frontend regression test).
- [x] `unheard serve --ssl-certfile/--ssl-keyfile` (3 tests); HTTPS shell/API/token behaviour checked on loopback.
- [x] Blind listening page and Gemma rating sheet with honest summaries (`scripts/m6_listening_page.py`, `scripts/m6_ratings.py`).
- [x] Final gates re-run after the fixes; see `M6-FINAL-REPORT.md` for exact counts.
- [ ] Owner actions: Android test, listening ratings, Gemma ratings, demo recording, publish. See `FINAL-PUBLICATION-CHECKLIST.md`.

## Human/device release gates — open

- [ ] Android: trusted HTTPS, real microphone, install/uninstall, safe areas, outdoor touch/contrast and reconnect.
- [ ] Screen lock/background interruption: verify honest stop/save behavior; never promise continuous capture.
- [ ] Physical headphone/speaker listening: check clipping, volume, source identity, groove, sections and ending.
- [ ] Gemma blind A/B human rating: `eval/m6/gemma_human_rating.csv` (six criteria) is blank; `eval/m5/human_rating.csv` remains unrated.
- [ ] Keyboard/screen reader and Safari/Firefox manual checks; large-library and mobile battery/thermal checks.
- [ ] Owner reviews current screenshots, interaction walkthrough, public-source audit and final diff.
- [ ] Use personally captured/explicitly cleared audio for the public video; no unlicensed evaluation clips.
- [ ] Confirm competition eligibility/write-up/template and deadline on the live challenge page.
- [ ] Explicit approval to push the branch, and separate approval before merging main or exposing a service.

## Local musical review prepared

Regenerate the matched A/B excerpts and the blind listening page (nothing is copied to Git; `server/data/` is ignored):

```bash
cd server
uv run python ../scripts/m4_6_compare.py --out data/m4_6
uv run python ../scripts/m6_listening_page.py --root data/m4_6    # then open data/m4_6/listening/index.html
```

Natural, Urban and Hybrid sets x Legacy / Organic / Composed, matched to -20.0 LUFS, shuffled labels, six-criterion rubric,
CSV export. Instructions and rubric: `docs/HUMAN-REVIEW.md`. These are ESC-50-derived local evaluation excerpts whose
individual source licences are not cleared for publication. No human listening or rating is claimed.

## Five experience questions

| Question | Technical evidence | Human verdict |
| --- | --- | --- |
| Why should I go outside? | Prologue and Field mission expose a concise recording goal | Unanswered: outdoor first-use session |
| Does teaching feel consequential? | Real memory altered held-out rankings; correction UI acknowledges committed state | Unanswered: player experience |
| Does the world visibly evolve? | Empty Chamber → real specimens/edges/labels → persisted milestones/remembered phase | Screenshots supplied; human review pending |
| Is music connected to sources? | Actual recorded bytes, source traces, stems and event-driven specimen activity | Unanswered: listening |
| Is the ending earned? | Backend unlock requires a ready composition from ≥3 annotated sounds; reload persists it | Technical gate passed; emotional verdict pending |

## Reproduce / approve

Use README setup commands and a disposable `UNHEARD_DATA_DIR`. Run heavyweight model checks sequentially.
The integration report distinguishes automated microphone input, actual laptop capture and untested physical phones.
After review, push `feat/release-integration` only with approval. Its merge commits already contain both source branches;
do not cherry-pick their commits again. Merge this complete branch into the intended target only after approval and checks.
