# Visual grammar v1 — how a sound becomes a specimen

Generator version: **1** (`server/unheard/visual/signature.py`, `web/src/visual/signature.ts`).
Same recording + same generator version ⇒ identical parameters, seed and geometry (tested).

**Honesty rule.** Everything in the `geometry` block is a bounded, documented transformation of a
*measured* quantity (DSP v1). The *mapping itself* is an artistic choice, not a scientific
interpretation: a "spiky" outline means "high spectral centroid", nothing more. Labels and
memory touch **only** the `semantic` block (hue, state, solidity). The `geometry_hash`
excludes `semantic`, so a correction never changes a specimen's shape — only its colour and
how resolved its outline looks.

## Where things are computed

| Step | Where | Why |
|---|---|---|
| DSP features, embeddings, memory | server (M1/M2) | scientific record, versioned |
| Visual parameters (≈ 6 KB JSON per recording) | server, persisted in `visual_artifact` | one deterministic source of truth; cheap to rebuild; browser never sees raw feature arrays or 512-d embeddings |
| Geometry (polylines), drawing, animation, export | browser (Canvas 2D, seeded PRNG) | render at any size/DPR; no large payloads |
| Similarity graph + 2-D layout | server, persisted in `atlas_state` | positions must be stable across reloads and clients |

Renderer: **Canvas 2D** (no WebGL/Three.js). A 100-node atlas with glyph outlines draws in a
few milliseconds; animation runs only while audio plays; `prefers-reduced-motion` disables
playback motion.

## Mappings (input → transformation → visual → reasoning → bounds)

| Visual | Input (measured) | Transformation | Artistic reasoning | Bounds |
|---|---|---|---|---|
| Outline radius `ring[128]` | RMS envelope (dBFS per STFT frame) | resample to 128, (dB+60)/60 clamped | the loudness profile *is* the body of the sound; loud passages bulge | 0…1 |
| Fold symmetry `symmetry_order` | spectral flatness (median) | `2 + round(6·(1−flatness))` | tonal sounds (bells, hum) feel regular; noise feels irregular | 2…8 |
| Radial jitter `jitter` | spectral flatness (median) | identity | noisy sounds get a ragged edge; where the raggedness lands comes from the seed | 0…1 |
| Spikes / crispness `sharpness` | spectral centroid (median, Hz) | `(log10 f − log10 150) / (log10 8000 − log10 150)` | bright sounds read as sharp; mitered joins above 0.5 | 0…1 |
| Stroke gaps `fragmentation` | spectral flux median / max | ratio | changing spectra break the outline into dashes | 0…1 |
| Radial ticks `ticks[]` | onset times | `t / duration` | each detected event is a mark on the dial | ≤ 96 ticks |
| Inner rings `bands[32]` | log-mel band means (dB) | resample 64→32, (dB+100)/100 | the spectral texture as faint concentric rings | 0…1 |
| Size `scale` | duration | `0.6 + 0.4·log-scaled(3…30 s)` | longer recordings are physically larger specimens | 0.6…1 |
| Stroke weight `energy` | RMS (dBFS) | `(dB+60)/50` clamped | louder sounds are drawn with a heavier line | 0…1 |
| Playback breathing | RMS envelope timeline (256 pts) | outline scales 0.9…1.1 with `envelope(t)` | the body swells with the recorded loudness, synced to `audio.currentTime` | — |
| Playback brightness | spectral flux timeline (128 pts) | fill lightness +0.25·`flux(t)` | spectral change flashes through the form | — |
| Onset glow | onset times | tick glow decays over 350 ms after each onset | events ring as they pass | — |
| Hue | **label** (confirmed, else top fused hypothesis) | `label.hue_seed` (stable hash of the slug) | the only label-driven property; a correction recolours, never reshapes | 0…359 |
| Outline solidity / dashing | **state** from annotation + novelty | confirmed solid · hypothesis solid-thin · uncertain long dashes · unknown short dashes + second offset outline | uncertainty is visible as an unresolved boundary | — |
| `resolution` | nearest-exemplar cosine, fused margin, annotation | 0 (user says unknown) … 1 (confirmed) | fill opacity | 0…1 |

Not used (and why): pitch contour (no f0 tracker in DSP v1), MFCCs (no consumer), the raw
embedding (512-d values are not a geometry; similarity is shown in the atlas instead).

## Invalid / extreme input

NaN/Inf features are replaced before mapping; silence gives a zero ring, zero energy and no
ticks (a thin, empty circle); clipped signals saturate `energy` at 1. All of this is tested
(`server/tests/test_visual.py`, `web/src/components/m3.test.tsx`).

## Versioning

| What | Version field | Change ⇒ |
|---|---|---|
| source audio | `recording.content_hash` | new seed, new specimen |
| DSP | `visual_artifact.dsp_version` | parameters recomputed on next access |
| embedding model | `visual_artifact.model_version_id`, `atlas_state.model_version_id` | semantic layer may change; atlas layouts are per model version, never mixed |
| generator | `visual_artifact.generator_version` | new row per version; v1 rows stay readable |
| layout | `atlas_state.layout_version`, `atlas_version` counter | bumps whenever a node is placed or the basis is refit |

## Atlas layout (doc 05 §4, ADR-009)

PCA on the pooled embeddings of the current model version. Fewer than 3 nodes: polar seed
positions. 3–7 nodes: basis refit on each change (tiny sets). ≥ 8 nodes: basis **frozen** and
persisted; new nodes are projected and nudged ≤ 0.08 units away from overlaps; existing nodes
never move; `POST /api/atlas/rebuild` refits explicitly. The 2-D picture keeps only the
reported `explained_variance_2d` of the spread (65 % on the development data) — distance in the
atlas is an approximation of "how alike they sound", nothing else.

Edges: `acoustic` = k=3 nearest neighbours with cosine ≥ 0.45; `shared_label` = same active
confirmed source label, each node linked only to its 2 most similar same-label nodes (no
cliques). Anchors = centroid of a label's confirmed nodes with their spread. Un-embedded
recordings (no inference yet, or a different model version) sit on an outer ring.
