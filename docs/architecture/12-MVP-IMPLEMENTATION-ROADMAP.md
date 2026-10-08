# 12 — MVP Implementation Roadmap

Deadline: **Oct 11 11:59 PM PDT** (= Oct 12 06:59 UTC). Today Oct 9. Effort is in focused hours [E]. Total ≈ 34 h; if less is available, cut per column.

**Non-negotiable vertical slice (VS-0), before any UI polish:** phone-or-file WAV → ingest → embedding+prediction → label via API → memory changes next prediction → 3-clip deterministic render. CLI/curl only. Target: end of M2.

Critical path: M0 → M1 → M2 → M4 → M6 (M3 and M5 hang off M2).

| M | Objective | Depends | Deliverables | Acceptance | Effort | Cut if late |
|---|---|---|---|---|---|---|
| M0 | Environment + model gate | — | uv venv py3.12, `scripts/verify_env.py`, `bench_models.py`, ADR update primary/fallback | CLAP or YAMNet embeds a 10 s clip; numbers recorded | 3 h | Skip CLAP, go YAMNet |
| M1 | Real audio pipeline | M0 | ingest (ffmpeg), DSP v1, SQLite schema/migrations, events/jobs, `POST /recordings`, `GET` detail; Field PWA recorder + IndexedDB queue + mkcert docs | upload→features+embedding stored; dup handled; ingest/DSP tests green; phone records and syncs on LAN | 8 h | Offline queue → simple retry |
| M2 | Learning + memory | M1 | kNN memory, fusion, novelty, annotations API, prototype/versioning, eval script v1 | cross-restart memory; before/after table generated; fusion tests green | 6 h | Prototypes (keep kNN only) |
| M3 | Visuals + atlas | M2 | fragment SVG v1, PCA atlas with stable placement, Lab views | geometry tests green; atlas stable on add | 5 h | Edges/animation |
| M4 | Music | M2 | planner det v1, renderer, schema, stems, export zip | seed-determinism + contribution tests green | 6 h | Melody role (rhythm+pad only) |
| M5 | Narrative | M2–M4 | state machine, templates, quests, truthfulness lint; optional Gemma | lint tests green; ECHO-0 lines tied to events | 3 h | Gemma |
| M6 | Validate + ship | all | outdoor test, eval report, README, 90-s video script, DEV post, repo public | AT-1 passes; honest results table | 3 h | Video → screenshots |

## Day plan
- **Oct 9 (remaining):** M0, M1 server half.
- **Oct 10:** M1 client, M2, VS-0, start M4.
- **Oct 11:** M3 minimal, M5 minimal, outdoor test, write-up, submit before 11:59 PM PDT; leave 3 h buffer.

## Deliverable gating
Do not start M3/M5 until VS-0 works. Ship what passes tests; mark the rest "planned" in README.
