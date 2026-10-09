# M3 Implementation Report — The Acoustic Atlas

Date: 2026-10-09 · Branch: `feat/m3-acoustic-atlas` (from M2 `9b48ea2`) · Status: **PASS** with
the limitations listed at the end.

## Visual engine

Renderer: **Canvas 2D** in the browser, parameters computed on the server (ADR-017).
No WebGL, no new rendering dependency. Generator version 1.

Pipeline: DSP summary + four stored arrays (RMS envelope, log-mel, centroid series, flux) →
`visual/signature.py` → ≈6 KB of bounded parameters (`geometry`, `animation`, `semantic`) →
`visual_artifact` row (seed = sha256(content_hash:version)[:8], label-independent
`geometry_hash`) → `web/src/visual/signature.ts` builds a 256-point folded outline with a
seeded mulberry32 PRNG and draws it (static, animated, PNG/SVG export).

Mappings (full table in `docs/visual-grammar.md`): outline radius ← RMS envelope; fold
symmetry (2–8) ← 1 − spectral flatness; jitter ← flatness; crispness/spikes ← log spectral
centroid; dash gaps ← spectral flux ratio; one radial tick per onset; inner rings ← log-mel
band means; size ← duration; stroke weight ← RMS; playback breathing ← envelope timeline;
flash ← flux timeline; tick glow ← onsets. **Hue is the only label-driven property**; state
(confirmed / hypothesis / uncertain / unknown) controls dashing and solidity. All mappings are
documented as artistic choices over measured quantities, not as scientific interpretation.

## Acoustic atlas

Nodes: every recording with a specimen; embedded nodes (pooled CLAP embedding of the dominant
model version) take part in similarity and layout, others sit on an outer ring. Edges:
`acoustic` k=3 nearest neighbours with cosine ≥ 0.45; `shared_label` between recordings with
the same active confirmed source label, each node linked to its 2 most similar same-label
nodes (no cliques). Anchors: centroid + spread per label. Layout: PCA on embeddings, polar
seeds below 3 nodes, refit below 8, **frozen basis at ≥ 8** with projection + bounded nudge
(≤ 0.08 units) for new nodes, persisted positions; explicit `POST /api/atlas/rebuild`
(ADR-018). Explained variance of the 2-D projection is returned and shown (65 % on the
development data). Progression state (`first_observation → emerging_relationships →
learned_categories → new_concept`) is derived from edges and anchors, not from counts.
Different embedding model versions are never mixed in one graph (tested).

## Implemented files

Server: `storage/migrations/0003_visual_atlas.sql`, `storage/repos_m3.py`,
`visual/signature.py`, `visual/service.py`, `atlas/graph.py`, `atlas/layout.py`,
`atlas/service.py`, `api/atlas.py`, `api/schemas_m3.py`; hooks in `jobs/worker.py` (artifact
after each stage), `memory/service.py` (semantic refresh after annotations and re-scores),
`api/deps.py`, `app.py`; events `ArtifactRendered`, `AtlasUpdated`.
Web: `visual/prng.ts`, `visual/signature.ts`, `components/SignatureCanvas.tsx`,
`components/Specimen.tsx`, `components/Atlas.tsx`, nav + "Open visual memory" in `App.tsx`,
styles. Tests: `server/tests/test_visual.py`, `server/tests/test_m3_api.py`,
`web/src/components/m3.test.tsx`. Docs: `docs/visual-grammar.md`, `docs/api.md` (M3 section),
ADR-017…019, README, smoke checklist.

## API and persistence

`GET /api/recordings/{id}/visual`, `GET /api/atlas`, `POST /api/atlas/rebuild`.
Migration 0003: `visual_artifact` (one row per recording × generator version: seed, dsp
version, model version, geometry hash, params JSON, status) and `atlas_state` (per model
version × layout version: frozen basis blob, basis size, explained variance, positions JSON,
atlas version). No rendered pixels are stored; parameters are ≈6 KB per recording.

Event consumption is idempotent: artifacts are upserted on `(recording, generator_version)`;
`ArtifactRendered` is only emitted when geometry or the semantic layer actually changed;
deletion cascades `visual_artifact` and drops the node from the persisted positions.

## UI

Three views in one page: **Hearing** (M1/M2 panels + "Open visual memory"), **Specimen**
(large animated signature, original playback synced through `audio.currentTime`, export
PNG/SVG, mapping legend, "why unresolved" line for unknown/uncertain, your notes marked as
interpretation, similar memories, model/memory provenance, waveform + spectrogram toggle) and
**Atlas** (pan, wheel zoom, click to select, filter by name, uncertain-only, optional
"feelings" layer clearly labelled yours, reset view, ECHO-0 lines, measured draw time).

## Determinism

Server: same features + hash ⇒ identical params/seed/hash (`test_same_input_same_params_and_seed`);
different signals differ meaningfully with the expected direction of change
(tone vs noise vs clicks); labels change only `semantic`; NaN/Inf, silence and clipping are
bounded; artifact rows are stable across restarts. Browser: same params ⇒ identical outline
and identical SVG; seed change ⇒ different outline; unknown state ⇒ dashed hollow; label
change ⇒ same outline. Layout: repeated `GET /api/atlas` returns identical positions; adding
a ninth node moves none of the first eight; positions survive restart.

## Tests

| Suite | Result |
|---|---|
| `uv run pytest` (fast; M1+M2+M3) | **92 passed, 0 failed, 1 deselected** (real-model test) in 14 s |
| ruff / ruff format / mypy strict | clean |
| `npx vitest run` | **34 passed** |
| `tsc`, `vite build` | clean |

## Performance (measured, Chrome on Linux, i7-13700H)

| Measurement | Value |
|---|---|
| `GET /api/atlas` with 101 nodes / 205 edges (rebuild + layout each call) | 242 ms, 118 KB JSON |
| Atlas canvas draw, 101 nodes with glyph outlines + 205 edges | **2.7 ms** per frame (EMA shown in the UI) |
| Specimen params per recording | ≈ 6 KB; geometry built once per params object |
| 100 synthetic uploads → DSP + CLAP + specimen | 29 s upload, inference queue drained in ≈ 70 s |
| Deleting 100 recordings (cascade + re-score + atlas) | 4.4 s |

Not measured: memory usage, mobile viewport frame time, 1 000-node behaviour.

## Browser validation

Chrome (google-chrome-stable) on Arch Linux, desktop viewport: atlas with 1 and 101 nodes,
node selection panel, specimen of the real 30 s microphone recording (8-fold symmetry,
crispness 0.91, dashed "unresolved" outline with the "why unresolved" evidence), playback
animation visibly changing the outline. Firefox, Safari, phones: **not tested**.

## Risks and limitations

- The novelty gate (M2) marks most first recordings "unknown" while memory is empty; the
  atlas therefore starts with dashed nodes until the player teaches names. This is the real
  model state, but it makes the first minutes look uncertain by design.
- 2-D PCA keeps ~65 % of the embedding spread on the test data; clusters of similar sounds
  are faithful, fine-grained distances are not.
- Near-duplicate recordings stack (the nudge is bounded at 0.08 units); a "second visit" ring
  (doc 05) is not implemented.
- `GET /api/atlas` rebuilds artifacts and layout on every call (~250 ms at 100 nodes); no
  caching yet.
- No field demonstration with five outdoor recordings was recorded in this session; the
  reproducible demo uses the real-model integration test (ESC-50 clips) plus the browser
  smoke test on a real microphone recording. Screen capture: not made.
- Reduced motion is honoured (no playback animation) but was verified only by code/test.

## Git

Branch `feat/m3-acoustic-atlas`; one commit on top of `9b48ea2`; not pushed.

## M4 readiness

The symphony engine can consume: `audio_asset` canonical WAV; `feature_set` summary + `.npz`
arrays (RMS envelope, onset times, centroid/flux series, log-mel); `visual_artifact.params.animation`
(normalised envelope 256 pts, flux 128 pts, onsets) for audio-visual sync; `embedding` rows and
`/neighbours` for similarity-driven arrangement; `annotation`/`exemplar` for named sources;
`atlas` nodes/edges/anchors for spatialisation. Music must read these tables, not the atlas
renderer (ADR boundary kept).
