# M4.5 — Listening and Browser Validation

Date: 2026-10-09 · Branch `feat/m4-impossible-orchestra` (continues from `4d0cd4a`)

| Status | Value |
|---|---|
| Engineering | **PASS** for backend, build and tests; UI still **not verified in a browser** (see below) |
| Browser validation | **PENDING** — could not be completed here; manual checklist in §3 |
| Musical quality | **NEEDS REVIEW** — no human has listened. Nothing in this document says the music sounds good |

## 1. Audio artifacts (for you to listen to)

All files are git-ignored (`server/data/` in `.gitignore`). They are derived from **ESC-50
(CC BY-NC 3.0, local evaluation only)** clips, so **do not publish or redistribute them** (not
in the repo, the DEV post or a demo video) unless the individual clips' Freesound licences are
checked first — ESC-50's per-clip licences differ and the dataset as a whole is non-commercial.
Regenerate any time: `cd server && uv run python ../scripts/m4_demo.py`.

Full pieces (16-bit, 48 kHz stereo):

| Set | Path | Length | Size |
|---|---|---|---|
| A natural | `/home/misa/projects/dev-challanges/the-unheard/server/data/m4_demo/A_natural_master.wav` | 42.8 s | 8.22 MB |
| B urban | `/home/misa/projects/dev-challanges/the-unheard/server/data/m4_demo/B_urban_master.wav` | 43.1 s | 8.27 MB |
| C hybrid | `/home/misa/projects/dev-challanges/the-unheard/server/data/m4_demo/C_hybrid_master.wav` | 43.4 s | 8.34 MB |

25 s excerpts (the convergence section plus 8 s of lead-in, 50 ms fades):

| Set | Path | Length | Size |
|---|---|---|---|
| A | `/home/misa/projects/dev-challanges/the-unheard/server/data/m4_demo/excerpts/A_natural_excerpt.wav` | 25.0 s | 4.80 MB |
| B | `/home/misa/projects/dev-challanges/the-unheard/server/data/m4_demo/excerpts/B_urban_excerpt.wav` | 25.0 s | 4.80 MB |
| C | `/home/misa/projects/dev-challanges/the-unheard/server/data/m4_demo/excerpts/C_hybrid_excerpt.wav` | 25.0 s | 4.80 MB |

Stems (same folder; each stem is the same length as its master and they sum to it):

| File | Layer | Source clip | Enters |
|---|---|---|---|
| `A_natural_t1.wav` | texture | rain | introduction |
| `A_natural_t2.wav` | texture | wind | discovery |
| `A_natural_t3.wav` | percussion | water drops | discovery |
| `A_natural_t4.wav` | melody | chirping birds | convergence |
| `B_urban_t1.wav` | pulse | engine | introduction |
| `B_urban_t2.wav` | percussion | clock tick | discovery |
| `B_urban_t3.wav` | percussion | footsteps | discovery |
| `B_urban_t4.wav` | melody | car horn | convergence |
| `C_hybrid_t1.wav` | texture | vacuum cleaner | introduction |
| `C_hybrid_t2.wav` | texture | rain | discovery |
| `C_hybrid_t3.wav` | percussion | footsteps | discovery |
| `C_hybrid_t4.wav` | melody | church bells | convergence |

Also there: `*_plan.json` (every event with its source window), `report.json`,
`diag_before.json` / `diag_after.json`, `overview.png` (spectrograms).
The same source clips (`rain`, `footsteps`) appear in B and C on purpose, to hear context change.

Suggested listening order: each **excerpt** first, then the full piece, then individual stems of
whatever you found confusing. Use headphones once and speakers once.

## 2. Objective diagnostics (`scripts/m4_diagnose.py`)

Proxies for what a listener would notice; **not** a substitute for listening. Values are
"before → after" the two fixes described in §2.2.

### 2.1 Measurements

| Metric | A natural | B urban | C hybrid |
|---|---|---|---|
| LUFS (≈, BS.1770-style) | -18.0 → -18.0 | -18.2 → -18.1 | -18.2 → -18.2 |
| oversampled (4×) peak, dBFS | -0.99 → -0.99 | -0.96 → -0.99 | -0.94 → -0.93 |
| clipped samples | 0 → 0 | 0 → 0 | 0 → 0 |
| crest factor, dB | 20.7 → 19.8 | 21.5 → 20.7 | 22.1 → 21.2 |
| steady-background share (wash proxy) | 0.237 → 0.211 | 0.092 → 0.090 | 0.245 → 0.206 |
| — by section (after) intro/disc/conv/res | 0.43 / 0.26 / 0.15 / 0.40 | 0.11 / 0.09 / 0.09 / 0.09 | 0.54 / 0.23 / 0.14 / 0.49 |
| mean spectral overlap between layers | 0.212 → 0.212 | 0.516 → 0.514 | 0.549 → 0.555 |
| worst overlapping pair (after) | water drops × birds (t3,t4): 0.85 | t2,t3 (two percussion layers): 0.68 | rain × bells t1,t4: 0.90 |
| median clarity of hits/notes vs other layers, dB (t-order) | -4.6 / 1.6 → **1.8 / 3.8** | 8.0 / 0.2 / -4.7 / 0.2 → 5.0 / 2.7 / **-2.1 / -1.3** | -2.3 / 1.8 → **4.5 / 4.9** |
| weakest layer below loudest, dB | 6.1 → 4.5 | 1.7 → 4.0 | 3.8 → 3.3 |
| adjacent-bar hit-pattern similarity (1 = copy) | 0.06 → 0.07 | 0.54 → 0.47 | 0.02 → -0.10 |
| 3–8 kHz vs 250 Hz–1 kHz in loud frames, dB | -17.7 → -20.2 | -9.4 → -8.6 | -9.4 → -13.0 |
| section RMS dBFS intro/disc/conv/res | -36/-25/-17/-29 → **-29/-22/-17/-23** | -33/-25/-18/-30 → **-27/-22/-19/-25** | -36/-27/-19/-32 → **-29/-23/-19/-26** |
| spectral centroid Hz intro/disc/conv/res (after) | 2449 / 734 / 710 / 423 | 373 / 869 / 1024 / 889 | 2387 / 1007 / 1140 / 1412 |
| sample-slice events per second, same order (after) | 0 / 1.4 / 2.6 / 0 | 1.3 / 5.3 / 7.1 / 1.9 | 0 / 2.2 / 4.2 / 0 |

(In A and C the introduction and resolution contain only the sustained atmosphere layers, by design.)

What the numbers say, per question in the brief:

* **Loudness / peaks / clipping:** all three at ≈ −18 LUFS, peaks ≈ −1 dBFS, no clipped samples. The urban set needs 4.4 dB of limiting (peaky footsteps/clock), the others ≤ 2 dB.
* **Broadband wash:** the steady-background share is low in the convergence sections (9–15 %), so events do stand out there. The *intro* and *resolution* of A and C are 40–55 % steady background — expected, they are noise beds. My first reading of the spectrograms ("C is mostly wash") was too harsh for the full piece and right only for those two sections.
* **Spectral masking:** residual overlap is highest in C (rain bed vs church bell, 0.90) and B (two percussion layers, 0.68). The overlap measure is about *spectral distribution* and cannot improve with ducking; the clarity row is the one that does.
* **Repetition:** A and C do not repeat bar-for-bar (hit similarity ≈ 0). B is the most repetitive (0.47) and has a flat bar-level spectral profile (0.99), consistent with a steady grid of hits.
* **Transient harshness:** 3–8 kHz is below the low-mid region in every set (negative dB), so nothing flagged as harsh; this says nothing about how a single click *feels*.
* **Source separation:** every layer is audible (clarity and share), the weakest is 3–5 dB under the loudest. Hits in B's footsteps layer (-2.1 dB) and the car horn (-1.3 dB) are still partly buried.
* **Musical development:** section RMS rises to a clear convergence in all three, centroid/density move between sections. B is "busy" from the second section (5–7 slice events per second).
* **Differences between the three:** roles, tempo (83 / 77 / 129 BPM), event counts (53 / 180 / 86) and spectra (centroids 0.4–2.4 kHz) differ, so they are not variants of one piece. Whether they *sound* different enough to a person is untested.

### 2.2 Defects found and changes made

Only changes backed by the numbers above:

1. **Hits/notes masked by the atmosphere beds** (median clarity −4.6 dB for A's water drops, −4.7 dB for B's footsteps, −2.3 dB for C's footsteps). Fix: atmosphere layers duck 4 dB under every slice of a percussion/accent/melody layer (15 ms attack, hold ≤ 0.4 s, 250 ms release); recorded in the plan (`ducking`) and applied to stems before the sum. Result: A 1.8 dB, C 4.5 dB, B −2.1 dB (improved, not solved). Also raised the percussion and accent base gain by 3 dB.
2. **Too wide a loudness spread between sections** (16–20 dB; the introduction at −36 dBFS RMS would likely vanish in a room). Fix: section offsets reduced (−9→−6, −5→−3, −8→−5 dB) and +1.5 dB per missing layer in thin sections (≤ +6 dB). Result: 11–12 dB spread, intros at −27 to −29 dBFS.

Not changed, deliberately: nothing was done about B's grid-like repetition, C's rain-vs-bell overlap, or pitch accuracy, because the evidence is a proxy and the right fix depends on how they actually sound.

Both changes are covered by new tests (`test_atmosphere_ducks_under_hits_and_only_there`,
`test_thin_sections_are_not_left_nearly_silent`).

## 3. Browser validation — PENDING

### What I tried

* The Claude-in-Chrome extension was not connected (twice).
* I then drove local Google Chrome 148 headless over the DevTools protocol (`scripts/m4_browser_check.mjs`, Node built-ins only; npm could not fetch Playwright).
* **Verified in real Chrome:** it launches; CDP works (`Runtime.evaluate`, `Page.addScriptToEvaluateOnNewDocument`, `Emulation`); `data:` pages load and evaluate.
* **Blocked:** every navigation to an `http://` page (the app, `/api/health`, even Chrome's own DevTools endpoint and a trivial Node server) stalls: the TCP connection is made, the request is never sent, and `Page.navigate` never completes. It is not the app. Tried: with/without `--disable-gpu`, `--no-sandbox`, SwiftShader, extensions off, background networking off, proxies off, private-network feature flags off, in-process network service, DevTools `Fetch` interception. No seccomp or network-namespace restriction is visible. I did **not** disable the tool sandbox or otherwise work around it without your say-so.
* So **none** of the following has been verified in a browser: source selection, composition creation from the UI, play/pause/seek, mute/solo, original vs transformed, timeline, provenance, atlas/specimen sync, export, save/reopen. They are covered only by jsdom unit tests with a fake Web Audio context (55 tests) and, for the API, by the Python tests and a live-server `curl` run.
* The script is written for all of these steps but has **never run past the page load**, so treat it as untested code.

### Defect found while preparing the browser run

Switching to the Atlas unmounted the Orchestra, which stopped playback and made the atlas reactions impossible. Fixed (the Orchestra stays mounted, hidden, once opened) and activity now goes dark when paused; unit tests updated. Still unverified in a browser.

### Manual checklist (5–10 minutes, Chrome desktop)

Setup: `cd web && npm run build`, then `cd server && uv run unheard serve` (model off is fine:
`UNHEARD_MODEL_NAME=none`), open `http://127.0.0.1:8000`, upload 5 clips (a bird, rain, wind,
footsteps, a horn or bell; 3–30 s each — the 25 s excerpts' *source* clips are in
`server/data/eval/esc50`). Open the browser console throughout.

| # | Do | Expect |
|---|---|---|
| 1 | Orchestra tab | all ready recordings are listed with checkboxes; "Compose from N" matches the ticks |
| 2 | Tick 4, press Compose | button shows progress, then Play appears within ~10 s; 4 layer rows with a specimen, role chip and "enters in …" |
| 3 | Play | sound starts; playhead and time advance; layers light up as their events sound |
| 4 | Pause, wait, Play | stops, holds position, resumes there |
| 5 | Drag the seek slider to the middle | sound jumps there; no glitch or double playback |
| 6 | M on one layer, S on another | that layer goes silent / only the soloed one is heard, immediately, while playing |
| 7 | "?" on a layer → 1 Original recording | the raw recording plays and the piece pauses |
| 8 | 2 Transformed layer | only that layer, from the piece |
| 9 | 3 Full composition | everything again |
| 10 | Click a bar on the timeline | "Where did that sound come from?" shows source seconds, role, pitch/rate; "Open its specimen" opens the right specimen |
| 11 | Click empty timeline space | playhead seeks |
| 12 | Play, then open the Atlas | the music keeps playing; nodes of sounding recordings glow and fade; pausing calms them |
| 13 | Export WAV | a .wav downloads and plays in any player; "with stems & plan" gives a .zip |
| 14 | Name it, Save, reload the page, Orchestra → "Saved & recent" | it reopens, plays, same content |
| 15 | Another variation | a different seed renders and plays |
| 16 | Resize to phone width | no horizontal scrolling |
| 17 | Console | no red errors |
| 18 | OS "reduce motion" on | specimen/atlas glow steps instead of easing |

Record anything that fails in the table at the end. If you want me to retry the automated run
in a different way (e.g. with your approval to run Chrome outside the tool sandbox), say so.

## 4. Human listening handoff

Please listen to the excerpts, then the full pieces. Score each item 1–5 (1 = bad, 5 = very
good) per set, and write a sentence where it matters. I will not mark musical quality PASS from
any number other than yours.

| Question | A natural | B urban | C hybrid | Notes |
|---|---|---|---|---|
| **Musicality** — does it feel like intentional music (beginning, development, ending)? | | | | |
| **Emotional impact** — does it make you feel something (calm, tension, curiosity)? | | | | |
| **Source recognisability** — can you tell what the recordings were, even transformed? | | | | |
| **Repetition** — is it varied (5) or does it loop/grind (1)? | | | | |
| **Mix clarity** — can you pick out individual layers; is anything buried or too loud? | | | | |
| **Artifacts** — clicks, harshness, pumping, odd pitch-shifts? (5 = none) | | | | |
| **Overall enjoyment** | | | | |

Plus, yes/no:

1. Do A, B and C sound clearly different from each other?
2. Is the quiet introduction audible enough on your speakers/headphones?
3. Does the melody layer (birds / horn / bells) sound like a melody, or like random pitched noise?
4. Would you listen to this a second time? Would you share it?
5. What is the single worst thing you hear, and in which set and time?

Pending: **human feedback — none received yet.**

## 5. Verification (rerun after the changes in §2.2 and the UI fix)

| Check | Result |
|---|---|
| `uv run pytest` (server) | **134 passed**, 1 deselected (`real_model`, needs CLAP weights), 0 failed, 0 skipped (includes the real-ESC-50 integration tests) |
| `ruff check`, `ruff format --check`, `mypy unheard` | clean, 83 files formatted, clean |
| `vitest` (web) | **55 passed** (8 files) |
| `tsc --noEmit`, `vite build` | clean, built (237 kB JS) |
| `node --check scripts/m4_browser_check.mjs` | syntax only; the script has not run end to end |
| Real-browser run | **not done** (§3) |

## 6. Remaining blockers

1. A person must listen (§4) before any musical-quality verdict.
2. The browser run (§3) must be done by hand, or by me if Chrome can be made to load `http://` pages in this environment (needs a decision about running it outside the tool sandbox).
3. Residual: B's grid-like repetition and low-clarity footsteps/horn, C's rain-vs-bell overlap, pitch tracking octave errors, and unproven cross-platform determinism.
