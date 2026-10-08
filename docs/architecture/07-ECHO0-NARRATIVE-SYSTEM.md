# 07 — ECHO-0 Narrative System

## Principle
ECHO-0 is a **state machine with a voice**, not a chatbot. It narrates only events that exist in the event log. Dialogue is selected/filled from templates by default; Gemma optionally rephrases them under constraints.

## Narrative state (derived from DB, not stored separately where possible)
`recordings_count, labels_count, exemplars_count, corrections_count, unknown_resolved_count, compositions_count, memory_version, last_events[]`

## Acts and unlock conditions (each tied to real state)
| Act | Unlock | What ECHO-0 can truthfully say |
|---|---|---|
| I The First Sound | first `PredictionGenerated` | "I heard {top-label?} — I'm {conf-band} sure." Shows waveform, features, first artifact |
| II A Name for Everything | ≥ 5 recordings and ≥ 1 `HumanAnnotationSubmitted` | Uses `Δ` from MemoryUpdated: "I mistook {A} for {B}." Only if a prediction was actually corrected |
| (II→V) The Sound I Cannot Name | an actual `novel=true` prediction occurs | Asks for a name; on label creation shows the diff in atlas + composition |
| III The Orchestra | ≥ 3 labelled recordings, ≥ 2 labels | Offers composition; reads the plan's real roles |
Acts IV–V of the full vision map as: IV = composition (MVP A3), V = unknown-resolution (inside A2 in MVP). City/Atlas = panel unlocked at ≥ 8 recordings.

## Truthfulness constraints (enforced in code)
1. Statement templates declare required event types; the renderer refuses to emit a line whose preconditions are absent (unit-tested).
2. "Heard" language only after an `inference_run` row for that recording. "Visited/saw/went" language is forbidden (lint list).
3. Three explicit provenance tags on every UI line: **model** (base prediction), **memory** (your labels), **imagination** (ECHO-0 prose). Prose is styled differently.
4. Counts and labels inside prose come from DB values at render time.

## Quest generator
Deterministic suggestions from gaps: least-represented label ("find something that sounds like {label} but different"), high-novelty prompts, missing contrast ("record something quiet"). Safety line on each: stay on public paths, don't approach animals, don't record people without consent (doc 10).

## Optional LLM layer
- Model: `gemma4:e4b-it-qat` is installed locally (6.1 GB) [V]; on a 6 GB GPU it will partially offload — **VERIFY latency**; fallback `gemma3:4b` (3.3 GB) [V present]. Never co-resident with CLAP on the GPU: run CLAP on CPU or serialize.
- Input: structured event JSON + tone guide. Output: ≤ 40 words, parsed; a post-check verifies numbers/labels appear verbatim from input and no forbidden verbs; failure ⇒ template line.
- ECHO-0 is fully playable with the LLM off.

## Example (from brief) as data
```json
{"event":"MemoryUpdated","correction":{"from":"wind","to":"water","recording":"rec_7f"},
 "line":"I mistook water for wind. Both move without keeping their shape.","tags":["imagination"]}
```
The correction is stored as structured data; the line is derived prose.
