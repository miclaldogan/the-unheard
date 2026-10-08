# 01 — Requirements and Scope

## Competition facts (verified 2026-10-09 via DEV Events API)
- Hacktoberfest Open-Source AI Challenge **Week 1 "Touch Grass"**, Oct 5 – Oct 11 2026, submissions due **Oct 11 11:59 PM PDT**.
- Prompt: open-source AI at the core; get people off the screen. Judging: **Writing Quality (weighted most)**, Relevance, Creativity, Technical Execution, optional partner use.
- Post must carry tag `#hf26challenge`, be a **new project built in the window**, one entry. Bonus for taking it outside and reporting.
- Partner categories include *Best Use of Gemma*. Policy here: Gemma is used only as the optional narrator/composition planner (see ADR-007); it is not added to qualify.
- Today is Oct 9: **~2.5 days remain**. The plan below is sized for that.

## Verified local environment (read-only inspection)
| Item | Value |
|---|---|
| OS / kernel | Arch Linux, 7.2.2-arch1-1 |
| CPU / RAM | i7-13700H (20 threads), 15 GiB total, ~4.6 GiB available at inspection |
| GPU | RTX 4050 Laptop, 6141 MiB VRAM; Intel iGPU default (use `prime-run`) |
| Python / Node | Python 3.14.7 (system), Node 26.8.1; `uv`, `npm`, `ffmpeg`, `sox` present; no pnpm |
| Python libs | numpy 2.5.2 only. **scipy, librosa, torch, onnxruntime, fastapi, sklearn missing** |
| Ollama models | gemma4:e4b-it-qat (6.1 GB), gemma3:4b, gemma3:12b, llama3.2:3b, qwen3:1.7b … |
| Browsers | google-chrome-stable, firefox. Mic: HDA analog capture present |
| Disk | 54 GB free |

Consequences: use `uv` with a pinned **Python 3.12** venv (3.14 wheels for torch/audio libs are a risk — VERIFY); RAM is tight, so keep the model on CPU or GPU one at a time and never co-load gemma with the audio model on 6 GB VRAM.

## Scope tiers
### MVP (must ship by Oct 11) — "3-act spine"
| # | Capability | Act |
|---|---|---|
| M1 | Phone/desktop recording → server, offline capture queue | I |
| M2 | Real embedding model inference + DSP features, persisted | I |
| M3 | Human labeling with kNN memory that changes later predictions; unknown handling | II |
| M4 | Feature-derived deterministic SVG artwork per recording | I–II |
| M5 | Minimal atlas (2-D PCA projection + stable incremental placement) | III |
| M6 | Deterministic sample-based composition from ≥3 recordings, WAV export, per-track solo | IV (reduced) |
| M7 | ECHO-0: templated dialog from real events; Gemma optional | all |
| M8 | Evaluation script: before/after personalization, determinism checks | — |

MVP acts: **A1 First Sound → A2 A Name for Everything (includes the "sound I cannot name" moment as unknown-label creation) → A3 The Orchestra.** Atlas appears in A2/A3 as a panel, not a separate act.

### Deferred
Full 5-act arc, UMAP, geographic mode, diffusion imagery/Riffusion, browser-side inference, multi-user, collaborative archives, memory decay UI, fine-tuning heads, Tone.js live mode.

## Cut order (first to go)
Gemma narrator → atlas edges/animations → per-track solo UI (keep render) → artwork variety → PWA install polish. **Never cut:** record→predict→correct→remember→compose vertical slice and the eval script.
