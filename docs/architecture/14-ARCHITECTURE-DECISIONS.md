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
