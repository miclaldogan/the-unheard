# Final publication checklist

Deadline: **October 11, 2026, 11:59 PM PDT** (October 12, 06:59 UTC; 09:59 in Istanbul). Confirm on the live challenge page
(`https://dev.to/challenges/hf26`) before submitting. One entry per person; the project must have been started inside the
challenge window (first commit here: October 9, 2026). Nothing below has been pushed, merged or published by the
engineering session.

## A. Repository audit (done by the session, on the tree at M6)

| Check | Result |
|---|---|
| Tracked media / weights / databases / keys / `.env` | none (`git ls-files` filtered for wav, ogg, mp3, flac, webm, m4a, bin, safetensors, gguf, pt, onnx, db, sqlite, pem, key, npz, .env) |
| Secrets scan of tracked files (AWS, GitHub, OpenAI-style keys, private-key blocks, key assignments) | no matches |
| Large files | largest tracked file is a ~1 MB PNG screenshot |
| Local filesystem paths in docs | removed from `M4-6-MUSICAL-REFINEMENT.md` and `M4-LISTENING-REVIEW.md` |
| Temp/log/backup files tracked | none |
| ESC-50 audio or derived audio in Git | none; the derived comparison audio is under ignored `server/data/` |
| `web/certs/`, `server/data/`, `dist/` | git-ignored |
| Reachable history | audited in M5.5 for private audio, databases, weights and likely secrets |

Re-run the same check on the final tree before pushing:

```bash
git ls-files | grep -iE '\.(wav|ogg|mp3|flac|webm|m4a|bin|safetensors|gguf|pt|onnx|db|sqlite|pem|key|npz)$|\.env$'   # expect nothing
git grep -nIE '(AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{30,}|sk-[A-Za-z0-9]{30,}|BEGIN (RSA |EC )?PRIVATE KEY)'             # expect nothing
git grep -nI '/home/'                                                                                                  # expect nothing
```

## B. Attribution and licences

| Component | Used as | Licence / terms | Status |
|---|---|---|---|
| This project | code | MIT (`LICENSE`) | ok |
| LAION-CLAP `laion/clap-htsat-unfused` | audio embeddings, CPU, downloaded locally | Apache-2.0 per its Hugging Face model card | **verify**: the card was not in the local cache; read it once and confirm before publishing |
| Gemma 3 4B (`gemma3:4b`, 4.3B parameters, Q4_K_M) via Ollama | local narrator | Gemma Terms of Use (confirmed from the local Ollama licence text) | ok. Weights are not redistributed; users pull them themselves |
| Ollama | local runtime | MIT | ok (not bundled) |
| ESC-50 | private evaluation only | CC BY-NC 3.0 with per-clip Freesound licences | **must not appear in the public demo or repo** |
| Python and JS dependencies | | `npm audit --omit=dev`: 0 vulnerabilities | licences not individually audited |

README, `docs/model-setup.md` and `docs/gemma-narrative-engine.md` state that personal learning is retrieval and that no model
is fine-tuned. Keep it that way in the article and video.

## C. Honesty of claims (read before each public sentence)

| You may say | You may not say (yet) |
|---|---|
| Local CLAP embeddings, retrieval memory, deterministic specimens, source-derived composition | "The AI learned / was retrained / was fine-tuned" |
| Gemma 3 4B runs locally, wording only, every line validated, template fallback | "Gemma improves the narrative" (human rating is PENDING) |
| 84.2% of Gemma's first attempts passed validation in my evaluation (57 calls) | any end-to-end success or fallback rate |
| Works in sandboxed desktop Chrome with a simulated microphone; laptop microphone captured once | "tested on Android / outdoors" until `ANDROID-FIELD-TEST.md` is filled in |
| Offline *capture* in the PWA | offline AI, background or locked-screen recording |
| Automatic quality checks flag Legacy but not Organic/Composed | "the music is better/beautiful" until humans rate it |

## D. Test gate (re-run on the final commit; record the numbers)

```bash
cd server
uv run ruff format --check . && uv run ruff check . && uv run mypy unheard
uv run python ../scripts/m5_export_schemas.py --check
uv run pytest                                          # default suite
HF_HOME=<cache with CLAP> HF_HUB_OFFLINE=1 UNHEARD_TORCH_THREADS=2 uv run --extra ml pytest -m real_model tests/test_real_model.py
uv run pytest -m real_gemma tests/test_narrative_real_gemma.py
cd ../web && npm run lint && npm run typecheck && npm run format:check && npm test && npm run build && npm audit --omit=dev
```

Actual results from the M6 session are in `M6-FINAL-REPORT.md`.

## E. Owner actions, in order

1. [ ] **Android test**: follow `ANDROID-FIELD-TEST.md`; fill the table; keep screenshots. (~45 min, includes going outside.)
2. [ ] **Listening review**: open `server/data/m4_6/listening/index.html`, rate Natural/Urban/Hybrid, export the CSV, run
       `python3 scripts/m6_ratings.py listening-summary <csv>`. (~25 min.) Decide which mode/set goes in the video.
3. [ ] **Gemma rating** (optional but strengthens the Gemma category): rate `eval/m6/gemma_human_rating.csv`, run
       `python3 scripts/m6_ratings.py gemma-summary`. (~20 min.) Report only what it shows.
4. [ ] **Record the demo** per `DEMO-FINAL-SCRIPT.md` with your own sounds. Export, check on speakers and headphones, frame-check
       for tokens, paths and private labels.
5. [ ] **Finish the article** `DEV-SUBMISSION.md`: replace every `[[OWNER: ...]]`, add your teammate's DEV username, the video, the
       screenshots with alt text, and the real outdoor paragraph. Set AI disclosure to `some_ai`. Paste into the official Week 1
       template on the challenge page and keep the `#hf26challenge` tag.
6. [ ] **Repository**: decide the public branch. At the time of writing, PR #1 (M5 backend) is open and unmerged on GitHub; the UI,
       integration and M6 work exist only on local branches. The public repository must contain the working project, so the
       release branch needs to be pushed and merged into the default branch. Give explicit approval for each step; the session will
       not push or merge on its own.
7. [ ] Add to the README any commit made after the deadline (a challenge rule).
8. [ ] Click Publish on DEV before 11:59 PM PDT on October 11. Check the post renders, links work and the video plays logged out.

## F. If time runs short (priority order)

1. A working public repo with an accurate README, plus an honest article. These cover the heaviest-weighted criterion.
2. A short, truthful demo (even 60 seconds, laptop-only) beats none.
3. The Android test and ratings can be reported as "pending" in the article's limits section. State that plainly.
4. Skip anything that needs a new feature. The release is feature-complete.
