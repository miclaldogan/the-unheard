# 13 — Risk Register

Ranked (likelihood × impact).

| # | Risk | L | I | Mitigation | Owner/trigger |
|---|---|---|---|---|---|
| 1 | **Time:** ~2.5 days for full scope | H | H | Strict VS-0 gate, cut order (doc 01), no UI polish before M2 | Re-plan at end of Oct 10 AM |
| 2 | **Model install/perf:** Py3.14 system python; torch/transformers wheels, CLAP memory on 15 GB RAM (4.6 GB free at inspection) | M | H | uv + py3.12; M0 gate; YAMNet fallback via adapter; close other apps; CPU-only inference | M0 |
| 3 | **Phone mic over HTTPS/LAN:** secure context + cert trust on phone, iOS quirks | M | H | mkcert doc; test early on M1; fallback: desktop mic + file upload for the demo; tunnel option | M1 day 1 |
| 4 | **Weak personalization gain** (embeddings don't separate user classes, wind/AGC) | M | M | Evaluate early (M2); report honestly; tune k/T; record-quality flags; fall back to prototype classifier | M2 |
| 5 | **Music sounds poor / unrecognisable** | M | M | Constrain roles by flatness; heavy use of sample slices; limiter; listener test; keep pad+rhythm only | M4 |
| 6 | Atlas instability or unreadable with few points | L | M | PCA basis only after 8 points; polar placement before | M3 |
| 7 | License surprise on weights/data | L | H | Record license in `model_version`; verify model cards before release; don't redistribute weights/ESC-50 | M0, M6 |
| 8 | GPU VRAM contention (6 GB) with Gemma | M | L | Gemma optional, serialized, templates default | M5 |
| 9 | LAN exposure of private audio | L | H | Bind localhost by default; token for `--lan` | M1 |
| 10 | Overclaiming ("AI learned") in the post | M | H | Copy rules; truthfulness lint; eval table in README | M6 |
