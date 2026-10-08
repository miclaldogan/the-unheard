# 05 — Audio-Visual Synthesis and the Acoustic Atlas

## 1. Three approaches, one decision
| Approach | MVP? | Notes |
|---|---|---|
| A Direct visualization (waveform, log-mel spectrogram) | **Yes** (Lab Mode instrument panels) | Honest depiction of measurements. |
| B Procedural, feature-driven generative art | **Yes** — the "memory fragment" | Deterministic from `(features, dsp_version, visual_version, seed)`. |
| C Generative imagery (CLAP→diffusion, Riffusion-style) | **No** — post-competition | A generated image is an *interpretation*, not evidence of the scene, and would need a multi-GB diffusion model on a 6 GB GPU shared with inference. UI would have to label it "imagined". |

## 2. Riffusion / spectrogram diffusion / inversion (research notes)
- Riffusion-style models generate **mel spectrogram images** with a diffusion model fine-tuned on spectrogram pictures, then invert to audio. Suited to *new music textures from text*; **unsuitable** for reconstructing a specific recorded scene, because the output isn't conditioned on the recording's phase or exact content [M].
- A magnitude spectrogram discards **phase**. Inversion needs an estimate: **Griffin–Lim** iteratively enforces STFT consistency; it yields audible "phasiness"/smearing and a metallic quality, worse on transients (birdsong clicks, footsteps) [M]. Neural vocoders (HiFi-GAN family) sound better but add dependencies and bias toward training-domain sound.
- Mel spectrograms are additionally **non-invertible without approximation** (mel filterbank is lossy).
- Consequence for us: **never invert a spectrogram to make the player's music**. The music engine uses the original waveforms (sampled/granulated), so provenance is exact. Spectrograms are for display and feature extraction only.

## 3. Visual grammar v1 (procedural artifact)
Each recording → one SVG "fragment" (a radial/polar plot). Geometry is a pure function of normalised features; `rng = PCG64(seed = first 8 bytes of content_hash)`.

| Visual property | Source feature | Mapping (all clamped to [0,1] by per-install running quantiles, falling back to fixed ranges) |
|---|---|---|
| Ring radius profile | RMS envelope (resampled to 128 pts) | r(θ) = r0 + a·rms(θ) |
| Spike sharpness / edge crispness | spectral centroid | stroke-linejoin miter↔round, spike angle |
| Symmetry order n | 1 − flatness (tonality) | n = 2 + round(6·tonality); noisy ⇒ asymmetry jitter |
| Fragmentation (gaps in stroke) | spectral flux | dash pattern length ∝ 1/flux |
| Radial ticks | onsets | one tick per onset at its time-angle |
| Curved overlay | f0 contour (if voiced ≥ 0.4) | Bézier path through log-pitch points |
| Hue | **top fused label** (hash→hue, stable per label id), saturation from confidence | — only element influenced by labels |
| Position in atlas | embedding | see §4 |

Rules: measurement-derived geometry **does not change** when a label is corrected; only hue/annotation text does (so "label corrections have predictable effects" is testable). A label-independent `geometry_hash` is stored for tests. Different recordings must differ: test asserts pairwise geometry distance > ε for distinct inputs.
Hypotheses [H] to be checked by eyeballing 10 recordings: the mapping gives visibly distinct shapes for wind vs birds vs traffic.

## 4. The Acoustic Atlas
Not a map. Nodes: recordings (shape = fragment), labels (anchors), unknowns (hollow nodes). Edges: kNN similarity above threshold (k=3). **Position = embedding similarity, not geography.** The legend states: "distance = how alike they sound". Geographic mode is deferred and would be a separate toggle with user-approved coarse (~1 km) location.

### Layout method
| Method | Use |
|---|---|
| PCA (2 components fitted on a frozen basis) | **MVP.** Deterministic, linear, cheap, and new points can be *projected* without moving old ones. |
| UMAP | Deferred. Non-linear/stochastic; incremental `transform` still shifts structure and adds a heavy dependency (umap-learn/numba). |
| Force-directed on kNN graph | Only for *local relaxation* of overlapping nodes (short, bounded iterations, pinned neighbours). |

### Stability strategy
- PCA basis is fit once when ≥ 8 recordings exist, stored as `atlas_basis(version)`, and **refit only when the user presses "re-center the atlas"** (or when explained variance of the 2-D projection of new points falls below a threshold, which prompts rather than auto-applies). Until the basis exists, positions come from a seeded polar placement by similarity to the first labelled exemplars.
- New point: `position = project(embedding)` + bounded repulsion against overlaps (≤ 20 px displacement; other nodes pinned).
- Layout state is versioned (`atlas_version`); the UI animates between versions.

### Event responses
| Event | Atlas reaction |
|---|---|
| New sound | node fades in at projected position; edges to 3 nearest drawn |
| Label corrected | node hue changes; nodes keep position; label anchor pulls gently (visual only, 200 ms) |
| New category | new anchor placed at centroid of its exemplars; unknown hollow node fills |
| Sound deleted | node dissolves; edges recomputed; no one else moves |
| Categories merged | anchors blend; hues unify |
| Re-recorded sound | near-duplicate detected; "second visit" ring added on existing node |
