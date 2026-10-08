# Manual browser smoke test (M1)

Run before claiming the milestone. Record the browser, OS and date next to each run.

Last run: 2026-10-09, Chrome (google-chrome-stable) on Arch Linux, built-in HDA mic, `http://localhost:5173` with Vite proxy. Firefox and a physical phone were **not** run.

Setup: `cd server && uv run unheard serve` and `cd web && npm run dev`; open `http://localhost:5173`.

| # | Step | Expected | Chrome Linux | Firefox Linux | Phone (LAN HTTPS) |
|---|---|---|---|---|---|
| 1 | Open the page | Masthead shows "server ok · dsp v1 · ffmpeg"; ECHO-0 says "I am ready to listen." | ✅ | not run | not run |
| 2 | Press Record | Browser mic prompt appears; after allowing, indicator turns red, timer counts, level meter moves with sound | ✅ (Chrome asked each time until 'Allow on every visit') | not run | not run |
| 3 | Make 4–6 s of environmental sound, press Stop | Indicator returns to "Captured"; preview `<audio>` plays back; status line shows seconds, format, size, peak | ✅ | not run | not run |
| 4 | Press Submit for analysis | Status walks uploading → processing → "preserved as …"; ECHO-0: "A signal has been preserved…" | ✅ | not run | not run |
| 5 | Analysis panel | Waveform drawn from server buckets; log-mel spectrogram visible; stat tiles show duration, RMS dBFS, centroid, etc.; inference row says "not run" | ✅ | not run | not run |
| 6 | Switch spectrogram tab to `stft` | Linear-frequency view loads | ✅ | not run | not run |
| 7 | Reload the page | Archive still lists the recording with status `ready` | ✅ | not run | not run |
| 8 | Press Play in the archive | Original upload plays | ✅ | not run | not run |
| 9 | Record < 3 s and press Stop | Submit is disabled; status says "too short" | not run in browser (reducer unit test covers it) | not run | not run |
| 10 | Submit a duplicate (record nothing new: resubmit is impossible, so upload the same file twice via curl) | Second upload returns 409 and the UI selects the existing recording | API only: curl ×2 → 202 then 409 with existing id; UI path not exercised | not run | not run |
| 11 | Press Delete | Row disappears; `data/audio/…/<id>` and `data/artifacts/…/<id>` are gone; GET returns 404 | ✅ files + rows gone | not run | not run |
| 12 | Deny the mic permission | ECHO-0: "I cannot hear without permission."; error shows `MIC_DENIED`; Clear returns to standby | not run | not run | not run |
| 13 | Stop the backend, press Submit | Error `NETWORK`; preview is retained; restart backend, Clear, Submit again succeeds | not run | not run | not run |
| 14 | Resize to 375 px width | Single column; Record button ≥ 150 px; table remains usable | ✅ 400 px window | not run | not run |
| 15 | Let recording run to 30 s | Auto-stop fires; file is submittable | ✅ auto-stop at 30 s; first run exposed a 30.01 s overrun bug, fixed by trimming PCM | not run | not run |

## M2 additions (hearing / teaching / memory)

| # | Step | Expected | Chrome Linux |
|---|---|---|---|
| 16 | Masthead | shows `ears: ready · clap-htsat-unfused · cpu` after first inference | |
| 17 | After submit | Hearing panel walks Analyzing → Hypothesizing; ranked table with ears cosine, memory —, fused score; ECHO-0 hypothesis line | |
| 18 | Teach: confirm top hypothesis + a descriptor | state → Remembered; memory panel shows 1 example under that name; ECHO-0 "You confirmed …" | |
| 19 | Teach: Correct this → reject top, name a new source | annotation history has 2 rows (active/superseded); learned names = 1; ECHO-0 "I called it … You called it …" | |
| 20 | Record a second similar sound | Hearing shows memory column filled for the taught name, evidence `memory`/`both`, neighbours list the first recording | |
| 21 | Mark a recording unknown | exemplars drop, ECHO-0 "You could not name it either." | |
| 22 | Delete an annotated recording | memory counts drop, other recordings re-scored | |
| 23 | Stop the backend mid-way | panels show a clearable `NETWORK` error; nothing fabricated | |
