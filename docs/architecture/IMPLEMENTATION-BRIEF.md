# Implementation Brief (for the coding agent)

**Build:** modular-monolith FastAPI server (Python 3.12 via `uv`) + Vite/React PWA. SQLite + files. See doc 02 for layout.

**Hard rules**
1. Raw audio and annotations are committed before any inference; failures never lose them.
2. Never say the model was fine-tuned. Only retrieval memory changes.
3. All DSP/visual/music outputs deterministic for `(input, version, seed)`; tests prove it.
4. ECHO-0 lines require their precondition events (lint-tested).
5. Don't add heavy deps (torch etc.) or download weights without the user's approval; M0 asks first.
6. No AI-attribution trailers in commits (user preference).

**Order:** M0 → M1 → M2 → **VS-0 gate** → M4 → M3 → M5 → M6 (doc 12).

**Decisions already made:** CLAP primary / YAMNet fallback behind `AudioModel`; fusion formula in doc 04 §3; PCA atlas with frozen basis; Python renderer with JSON-schema plan; Gemma optional.

**Open items needing measurement:** model install on Py3.12, latency/RSS, kNN hyperparameters (k, T, κ, τ), HTTPS-on-phone path, license verification of weights.

## First task — "M0/M1a: ingest + DSP skeleton, no ML"
Create `server/` package with: `pyproject.toml` (fastapi, uvicorn, numpy, scipy, soundfile; pinned), SQLite migrations `0001_init.sql` (tables from doc 08), `ingest` (ffmpeg → 48 kHz mono s16, hash, quality flags), `dsp` (RMS, centroid, flatness, flux, onsets, log-mel; `dsp_version=1`), `events`/`jobs`, `POST/GET /api/recordings`, and a `FakeAudioModel` implementing `AudioModel`.
**Files:** `server/unheard/{api,ingest,dsp,models,events,storage}/…`, `server/tests/test_ingest.py`, `test_dsp.py`, `test_api_recordings.py`, `scripts/verify_env.py`.
**Acceptance:** `uv run pytest` passes; synthetic sine/noise/click tests (doc 11) pass; duplicate upload → 409; corrupt upload leaves no row; two DSP runs produce identical hash; `GET /api/health` lists env info. Report which tests actually ran.
