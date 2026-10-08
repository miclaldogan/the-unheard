# M1 Implementation Report — Audio Foundation

Date: 2026-10-09 · Branch: `feat/m1-audio-foundation` · Status: **PASS** (with the explicit
limitations listed at the end)

## What was implemented

- `server/unheard/` (Python 3.12, FastAPI): config, RFC 7807 errors, SQLite (WAL) with numbered
  migrations, UUIDv7 ids, atomic blob store with path-traversal guards, ingest
  (magic-byte sniffing → ffmpeg decode → signal validation → canonical 48 kHz mono float32
  WAV → content hash → single-transaction commit of row + assets + job + event), DSP v1
  (STFT, mel bank, time/spectral features, onsets, waveform summary), in-process job worker
  with retries and crash recovery, event log, REST API, `unheard serve` CLI (refuses to bind
  non-loopback without a token), optional bearer-token auth.
- `server/unheard/models/contracts.py`: the `AudioModel` adapter boundary
  (`AudioInferenceInput`, `ModelInfo`, `LabelScore`, `Embedding`, `ModelError`,
  `InferenceResult` with `status ∈ {not_run, ok, failed, unavailable}`). Production returns
  `not_run`; a deterministic fake exists only in tests.
- `web/` (Vite + React + TypeScript): AudioWorklet PCM capture → 16-bit WAV
  (MediaRecorder fallback), pure-reducer recording state machine, API client with
  problem+json handling and polling, capture / analysis / archive panels, canvas waveform
  and spectrogram drawn from server data, static ECHO-0 lines, responsive layout, web
  manifest, Vite HTTPS + `/api` proxy wiring for LAN testing.
- Docs: README, `docs/api.md`, `docs/local-https.md`, `docs/smoke-test.md`, this report;
  `scripts/mkcert.sh`, `scripts/verify_env.py`.

## Dependencies actually installed

Python (pinned in `server/uv.lock`): fastapi 0.143, uvicorn, pydantic 2 + pydantic-settings,
python-multipart, numpy 2.5.3, scipy 1.18.1, soundfile 0.14.0; dev: pytest, httpx, ruff, mypy.
**librosa was not added**: everything it would have provided (STFT, mel bank, spectral stats,
onset novelty) is ~150 lines of NumPy/SciPy here, fully documented and deterministic, and it
avoids the numba/llvmlite weight. External binary: ffmpeg 9.0.1 (present on this machine).

Node (`web/package-lock.json`): react 18, vite 5, typescript 5, vitest 2, jsdom,
@testing-library/react + jest-dom, @types/node. No PWA/workbox plugin.

## Audio processing behaviour

1. Upload bytes are sniffed (RIFF/WAVE, EBML, ftyp, OggS, fLaC, ID3/MPEG sync). Client MIME and
   filename are stored as metadata only.
2. `ffprobe` reports codec/rate/channels; `ffmpeg -nostdin` decodes stdin → `pan=mono`
   with explicit equal channel weights (ffmpeg's default stereo→mono matrix uses 1/√2 gains and
   would raise RMS by 3 dB — caught by a test) → `aresample` to 48 kHz → f32le on stdout,
   with a 30 s timeout. Fallback without ffmpeg: libsndfile + `scipy.signal.resample_poly`
   (WAV/FLAC/OGG only). Both paths agree to 1e-6 on WAV (tested).
3. Validation on the decoded signal: NaN/Inf replaced (rejected if > 1 %), duration 3–30 s,
   RMS ≥ −60 dBFS, source rate 8–192 kHz; clipping, DC offset and "quiet" are **flags**.
   No normalisation or gain is ever applied.
4. `content_hash` = SHA-256 of the canonical float32 PCM → duplicate uploads return 409 with the
   existing id.
5. DSP v1 runs on the worker thread; results go to `features_v1.npz` (+ SHA-256) and a JSON
   summary in `feature_set`. Parameters and formulas are in the module docstring of
   `server/unheard/dsp/features.py`.

## Test results (all run on 2026-10-09)

| Suite | Result |
|---|---|
| `uv run pytest` (server) | **58 passed, 0 failed, 0 skipped** in ~5 s |
| `uv run ruff check` / `ruff format --check` / `mypy unheard` (strict) | clean |
| `npx vitest run` (web) | **17 passed** |
| `tsc --noEmit` | clean |
| `vite build` | ok (173 kB JS, 56 kB gzipped) |
| Manual browser smoke test (Chrome, Linux, real HDA microphone) | steps 1–8, 11, 14, 15 ✅; 9 and 10 covered by automated tests only; 12, 13 not run; Firefox and phone not run |

DSP tests cover: 440 Hz sine (centroid ±2 bins, flatness < 0.05, RMS = A/√2 ±0.1 %, ZCR = 2f/sr
±2/s), silence, seeded white noise (flatness > 0.4, centroid ≈ 12 kHz ±1 kHz, rolloff ≈ 0.85·Nyquist),
two-tone (centroid/rolloff), 4 Hz click train (density 4 ±0.4 /s, onsets within ±20 ms),
clipped sine (clipping ratio > 0.7, bandwidth rises), 16/44.1/48 kHz, stereo downmix,
1 kHz mel peak bin, filterbank shape, STFT energy stationarity, bit-identical determinism,
NaN/empty/short-signal handling.

Backend tests cover: health; upload → process → retrieve (features, mel + STFT spectrogram,
list); original bytes served back; unsupported/too-short/silent/undecodable/malformed →
415/422; oversized → 413; duplicate → 409; malformed and traversal ids → 404; delete removes
rows, files and leaves the event trail; processing failure → `failed` with inspectable error,
raw audio still playable, `retry` succeeds; persistence across app restart; `running` jobs
re-queued on restart; bearer token enforcement; webm/opus, mp4/aac, ogg/vorbis, mp3 uploads
(encoded with ffmpeg, i.e. what MediaRecorder sends); libsndfile fallback.

## Measurements (this laptop, i7-13700H, CPU only)

| Measurement | Value |
|---|---|
| e2e test, 5 s WAV: upload+ingest / upload→ready | 127 ms / 234 ms |
| e2e test, 5 s webm/opus: upload+ingest / upload→ready | 85 ms / 193 ms |
| Real 17.18 s mic recording (1.6 MB WAV): ingest + commit | ≈ 0.4 s (server log) |
| Real 17.18 s recording: DSP v1 | 0.266 s |
| Artifact sizes for 17 s | source 1.6 MB, canonical 3.3 MB, features .npz 2.2 MB |

RSS was not measured.

## Bugs found by the real-browser test (and fixed)

- The 30 s auto-stop delivered 30.01 s of PCM (one extra worklet block) → server rejected it
  with `AUDIO_TOO_LONG`. Fix: the client trims the PCM to exactly `max_duration_s` samples
  (MediaRecorder fallback stops 0.5 s early since it cannot be trimmed).
- After a failed submit the preview disappeared. Fix: `error` state keeps the preview and
  allows Submit/Discard.
- Header recording count did not refresh. Fix: health is refetched with the archive.

## Deviations from the architecture documents (all small, documented here)

| Doc | Decision | Deviation and reason |
|---|---|---|
| 03 §2 | rolloff, bandwidth, ZCR "dropped from MVP" | Implemented (task requirement). They are cheap, tested, and consumers can ignore them. |
| 03 §1 | canonical 48 kHz mono **s16** | Stored as **float32** WAV. Lossless w.r.t. the decoder output, keeps clipping measurements exact; s16 can be derived for any model that needs it. |
| 08 | delete = tombstone (id + hash) | Hard delete in M1. Tombstones exist to block silent re-import once exemplars/prototypes depend on a recording; that arrives with memory in M2. |
| 08 | `audio_asset` is one row per recording | Two rows per recording (`source`, `canonical`) so the original upload is preserved verbatim and the canonical file is separately addressable. |
| 02 | Field PWA with IndexedDB offline queue in M1 | Not implemented (roadmap doc 12 names this as the M1 cut). Documented in `docs/local-https.md`. |
| 10 | pairing token shown as QR in Lab | Token is an env var, passed once via `?token=` and stored in `localStorage`. QR UI deferred. |

Everything else (paths under `/api`, 202 + polling, problem+json codes, durability-first
ordering, job table + single worker, UUIDv7, content-hash dedupe → 409, WAL, migrations by
`user_version`, AudioWorklet-first capture) follows the docs.

## Remaining risks

- Phone capture over LAN HTTPS is wired but untested on hardware; mkcert CA install on iOS is
  fiddly. Budget 30–60 min on Oct 10.
- Chrome asked for mic permission on every click until "Allow on every visit" was chosen;
  the UI stays in "Requesting microphone" without explanation during the prompt. A
  pre-permission explainer (doc 09) would help; not built.
- `/api/recordings/{id}/spectrogram` returns JSON (~0.3 MB for 30 s at 600 frames); fine
  locally, would want PNG/binary over a slow LAN.
- One global SQLite connection behind an RLock: correct, but the request thread blocks while
  the worker holds a transaction (milliseconds).
- No CSRF/origin protection beyond the CORS allow-list; acceptable for loopback.

## Known limitations

No recognition, embeddings, memory, atlas, visuals or music. No offline queue, no service
worker, no Firefox/Safari/phone verification, no RSS measurement, no QR pairing. Hard delete
instead of tombstone. See README "Current limitations".

## What M2 needs from M1 (all in place)

- `AudioInferenceInput` built from the canonical WAV (`AudioAssetRepo.get(kind="canonical")`).
- `AudioModel.infer()` → `InferenceResult`; persist into new `model_version`, `embedding`,
  `prediction` tables (migration `0002`), run as a second job stage (`stages["embed"]`).
- `RecordingDetail.inference` already carries the contract shape; swap `not_run` for real
  results and ECHO-0 may then say "I heard".
- Tombstone-on-delete and exemplar retraction once annotations exist.
