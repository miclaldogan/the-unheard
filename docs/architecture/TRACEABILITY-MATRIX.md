# Traceability Matrix

| Requirement | Component(s) | Milestone | Test(s) |
|---|---|---|---|
| Real open-source AI central | `models` (CLAP/YAMNet), `memory` | M0, M2 | model smoke, learning eval |
| Field recording, offline capture | Field PWA, IndexedDB queue, `ingest` | M1 | AT-2, ingest tests |
| Local-first/private | storage, API auth, health | M1 | privacy checks, token test |
| User feedback causes state change | `memory`, annotations API | M2 | memory unit tests, AT-1 step 2–4 |
| Unknown ≠ fabricated certainty | novelty detector | M2 | AT-3, novelty unit test |
| Personalization improves predictions | fusion + eval | M2 | `eval/run_eval.py` before/after |
| Persistence across sessions | SQLite | M1–M2 | restart test (AT-1.4) |
| Visuals depend on acoustics | `visual` | M3 | geometry determinism/difference tests |
| Atlas visual continuity | `atlas` | M3 | stability tests |
| Music traceable to recordings | `music` | M4 | contribution + determinism tests |
| Plan validated, LLM optional | planner + schema | M4–M5 | schema tests, LLM-fallback test |
| ECHO-0 never claims unreal events | `echo0` | M5 | precondition + lint tests |
| Reproducible demo & write-up | eval, docs | M6 | AT-1, outdoor protocol |
| Minimal screen time | Field Mode design | M1, M6 | screen-on log in outdoor protocol |
