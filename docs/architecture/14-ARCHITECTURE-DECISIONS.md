# 14 — Architecture Decision Records

Format: Decision · Rationale · Alternatives · Revisit when.

**ADR-001 Modular monolith (Python/FastAPI) + React PWA.** One process, typed module interfaces. *Alt:* microservices (no scaling need), Node backend (audio/ML libs are Python-native). *Revisit:* multi-user hosting.

**ADR-002 SQLite + filesystem; IndexedDB only as phone queue.** *Alt:* Postgres/Mongo (ops cost), OPFS (no benefit), vector DB (<10⁵ vectors). *Revisit:* >50k embeddings.

**ADR-003 In-process event log + job table; no broker.** Transactional outbox, idempotent handlers. *Alt:* Celery/Redis/queues. *Revisit:* concurrent users.

**ADR-004 Primary model LAION-CLAP, fallback YAMNet, behind `AudioModel` adapter.** Needs M0 confirmation. *Alt:* PANNs, BEATs, AST (see doc 03). *Revisit:* if M0 gate fails.

**ADR-005 Inference on laptop; phone = offline capture only.** We will not advertise offline AI on phone. *Alt:* in-browser ONNX/TF.js (unverified feasibility, bigger bring-up). *Revisit:* post-competition with YAMNet.

**ADR-006 Offline deterministic Python renderer; browser plays files.** *Alt:* Tone.js/Web Audio live (non-reproducible, harder to test). *Revisit:* interactive mode.

**ADR-007 Gemma optional, via Ollama, narrator + plan suggestions only, validated.** Installed models present locally [V]. Not an audio model and not required, so we don't claim it as core. *Alt:* no LLM (always supported), llama3.2:3b/qwen3:1.7b. *Revisit:* if latency fits.

**ADR-008 Retrieval memory instead of fine-tuning.** Reliable, instant, explainable, reversible. *Alt:* LoRA/head training (deferred).

**ADR-009 PCA stable basis for atlas; UMAP deferred.** Stability requirement.

**ADR-010 Client-side PCM capture (AudioWorklet) over MediaRecorder-first.** Avoids codec variance. *Alt:* MediaRecorder (kept as fallback).

**ADR-011 No spectrogram inversion/diffusion in MVP.** Phase loss, provenance loss; see doc 05.

**ADR-012 Python 3.12 via uv, not system 3.14.** Wheel availability risk; VERIFY in M0.

**ADR-013 (M2) CLAP confirmed as primary; YAMNet not installed.** Gate measured on 184 real ESC-50 clips, CPU: load 6.3 s, 0.2 s per 10 s window, 1.1 GB RSS, zero-shot top-1 0.73 / top-3 0.90 over a 39-label vocabulary, kNN recall@5 0.978. *Alt:* YAMNet (needs TensorFlow; closed vocabulary). *Revisit:* if CPU latency becomes a problem on the field laptop.

**ADR-014 (M2) Fusion uses one global λ from relevant memory evidence, not a per-class λ_c.** Doc 04 §3's per-class λ_c leaves labels with zero exemplars at their pure base score, so memory can never overrule the ears (five consistent corrections "water→wind" still ranked water first in tests). λ = n_rel/(n_rel+κ) with n_rel = kNN exemplars whose cosine ≥ τ_n; memory distribution mixed with a uniform floor α=0.1. Base cosines are recomputed from stored window embeddings against the current label space so user-created names take part without re-running the audio model. *Revisit:* with calibrated per-class temperatures once ≥10 labelled eval examples per class exist.

**ADR-015 (M2) Novelty gate = nearest-exemplar cosine AND (low margin OR high entropy).** Doc 04 §4's three-way AND never fired on ESC-50; the nearest-exemplar cosine alone has AUROC 0.95 for a never-taught class. Defaults τ_n=0.55, τ_m=0.60, τ_e=0.25 flag 54 % of unknown-class clips at a 5 % false-flag rate (eval/reports). Thresholds are configuration, not guarantees.

**ADR-016 (M2) Hard delete instead of tombstones remains.** Deleting a recording cascades embeddings, predictions, annotations and exemplars, recomputes prototypes and re-scores the rest. Tombstones still deferred.

**ADR-017 (M3) Visual parameters are computed and persisted server-side; geometry is rendered in the browser with Canvas 2D.** The server owns the scientific→visual mapping (one deterministic implementation, versioned, ≈6 KB per recording); the browser owns drawing, animation and export, so raw feature arrays and 512-d embeddings never leave the server for the visual path. *Alt:* SVG generated server-side (bigger payloads, no playback animation), WebGL (unneeded below ~1 000 nodes). *Revisit:* above ~1 000 nodes.

**ADR-018 (M3) Atlas basis freezes at 8 nodes, not doc 05's "≥ 8 and user action only".** Below 8 the set is refit on change (tiny, movement is harmless); at ≥ 8 the PCA basis is persisted and new nodes are projected + nudged (≤ 0.08) with every other node pinned; `POST /api/atlas/rebuild` refits explicitly. Explained variance of the 2-D projection is reported in the UI.

**ADR-019 (M3) Playback animation uses precomputed timelines, not a live analyser.** Envelope (256 pts), flux (128 pts) and onset times ship with the visual parameters; the renderer samples them at `audio.currentTime`. Exact, cheap, deterministic, works for seek/replay; the Web Audio analyser would add CPU, be non-deterministic and could stall playback.

## M4 decisions (implemented)

**ADR-020 Music is rendered offline by a deterministic NumPy/SciPy renderer; the browser plays rendered stems.** Stems and master are written once, the master SHA-256 is stored, and the same inputs + seed give identical bytes on one machine. *Alt:* Tone.js/live Web Audio synthesis (non-reproducible, harder to test, no export). The browser still uses Web Audio for stem playback so mute/solo are gain changes on one clock. *Revisit:* a live "play with the sliders" mode.

**ADR-021 Roles come from measurements, never from labels; a missing capability makes a role unassignable.** Pitch (YIN) gates melody and key; noise can never yield either. Power-domain spectral flatness is not used for "noisiness" because it is tilt-dominated on real recordings. *Alt:* label → instrument table (explicitly rejected: two water recordings must not sound alike). *Revisit:* learned role classifier once enough human corrections exist.

**ADR-022 Deleting a recording deletes the compositions that contain it; compositions store plain recording ids (no FK) and render one at a time.** Privacy beats convenience: those files contain the recording's audio. One render at a time bounds RAM (≈1.1 GB peak for 8 sources × 60 s). *Alt:* keep compositions as "orphaned" derivatives; concurrent renders. *Revisit:* an explicit "keep this piece" confirmation.
