# 02 — System Architecture

**Style: modular monolith.** One Python process (FastAPI) with internal packages having explicit interfaces; one React PWA; SQLite + filesystem. No queues, vector DB, or microservices (ADR-003).

## System context
```mermaid
flowchart LR
  P[Player]
  subgraph Phone[Phone - Field Mode PWA]
    REC[AudioWorklet recorder] --> Q[(IndexedDB capture queue)]
  end
  subgraph Laptop[Laptop - Lab Mode + Server]
    UI[Lab Mode UI]
    API[FastAPI monolith]
    DB[(SQLite)]
    FS[(data/audio, artifacts, renders)]
    OLL[Ollama gemma - optional]
  end
  P --> REC
  Q -- sync over LAN HTTPS --> API
  P --> UI --> API
  API --> DB
  API --> FS
  API -. optional .-> OLL
```

## Components
```mermaid
flowchart TB
  subgraph server[unheard server package]
    ING[ingest: validate, decode, normalize]
    DSP[dsp: features]
    MOD[models: AudioModel adapter - CLAP / YAMNet]
    MEM[memory: kNN + prototypes + fusion + novelty]
    ATL[atlas: projection + layout state]
    VIS[visual: feature to SVG geometry]
    MUS[music: planner + deterministic renderer]
    AGT[echo0: state machine + templates + optional LLM]
    EVT[events: append-only log + handlers]
    STO[storage: SQLite repos + blob store]
  end
  ING --> EVT
  EVT --> DSP --> EVT
  EVT --> MOD --> EVT
  EVT --> MEM --> EVT
  EVT --> ATL
  EVT --> VIS
  EVT --> MUS
  EVT --> AGT
  STO --- EVT
```
Boundary rule: modules talk only through (a) typed function interfaces in `contracts/` and (b) events. No module imports another's internals.

## Core event chain
`RecordingCaptured → FeaturesExtracted → PredictionGenerated → HumanAnnotationSubmitted → MemoryUpdated → AtlasUpdated → CompositionUpdated`

Implemented as an **in-process synchronous pipeline with a persisted event log and job table**; handlers run in a single worker thread (inference is the bottleneck, not I/O).

### Guarantees
- **Durability first:** the raw WAV and `recording` row are committed *before* any processing. Inference failure leaves `processing_job.status='failed'` with error; the recording and any later label survive.
- **Idempotency:** each event has `event_id` (UUIDv7) and handlers key on `(recording_id, stage, algo_version)`; reruns upsert. Upload dedupes on SHA-256 of normalized PCM (`recording.content_hash` UNIQUE per install).
- **Retries:** up to 3, exponential backoff, only for stages flagged retryable (model load OOM yes, corrupt file no).
- **Consistency:** each handler writes its outputs + next event row in one SQLite transaction (transactional outbox). At-least-once delivery, idempotent handlers → effectively once.
- **Human labels never depend on inference:** `HumanAnnotationSubmitted` is accepted even if predictions are missing; memory update needs only the embedding, which is re-queued if absent.

## Sequence: audio processing
```mermaid
sequenceDiagram
  participant C as Client
  participant A as API
  participant I as Ingest
  participant D as DSP
  participant M as Model
  participant K as Memory
  C->>A: POST /recordings (wav/webm/m4a)
  A->>I: validate, ffmpeg to 48k mono s16
  I-->>A: recording_id (committed)
  A-->>C: 202 recording_id
  A->>D: features v1
  A->>M: embedding + base probs
  A->>K: fuse(base, memory)
  K-->>A: Prediction (top-k, confidence, novelty)
  A-->>C: SSE: prediction ready
```

## Sequence: learning feedback
```mermaid
sequenceDiagram
  participant U as Player
  participant A as API
  participant K as Memory
  participant T as Atlas
  participant V as Visual
  participant G as ECHO-0
  U->>A: POST /recordings/id/annotations {labels, source}
  A->>K: add exemplar(s), recompute prototype, bump memory_version
  K-->>A: MemoryUpdated(version, delta)
  A->>T: place/reposition (stable layout)
  A->>V: restyle artifact (label hue only)
  A->>G: event to narrative state
  A-->>U: diff: what changed (re-scores of past recordings)
```

## Sequence: music
```mermaid
sequenceDiagram
  participant U as Player
  participant A as API
  participant P as Planner
  participant R as Renderer
  U->>A: POST /compositions {recording_ids, seed}
  A->>P: deterministic plan (or LLM plan, schema-validated)
  P-->>A: plan.json
  A->>R: render(plan, audio, seed)
  R-->>A: master.wav + stems/ + provenance
  A-->>U: composition_id, stems list
```

## Deployment topology
Primary: laptop runs server bound to LAN with HTTPS (mkcert cert, because `getUserMedia` needs a secure context). Phone installs PWA, records offline, syncs when on the same network. Alternative: a temporary quick tunnel for demos (a remote relay — UI must label it as such). Raw audio goes to the laptop only. True offline *inference* on the phone is **not** an MVP claim: phone = offline capture, laptop = inference.

## Repository layout (to be created in M1)
```
the-unheard/
  server/unheard/{ingest,dsp,models,memory,atlas,visual,music,echo0,events,storage,api}/
  server/tests/  server/pyproject.toml
  web/ (Vite + React + TS) src/{field,lab,components,state}/
  contracts/ (JSON Schema: events, composition plan, API)
  eval/ (datasets README, run_eval.py, reports/)
  scripts/ (verify_env.py, fetch_models.py, mkcert.sh)
  docs/architecture/
  data/ (gitignored)
```

## Container diagram note
Single deployable: `uv run unheard serve` serves API and the built `web/dist`.
