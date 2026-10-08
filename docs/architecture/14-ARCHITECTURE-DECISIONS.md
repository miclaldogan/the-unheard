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
