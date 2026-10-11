# M7: publishable synthetic audio

The project could demonstrate itself only with ESC-50, which is CC BY-NC with per-clip Freesound licences and
therefore **must not appear in a public demo or in Git**
([`FINAL-PUBLICATION-CHECKLIST.md`](FINAL-PUBLICATION-CHECKLIST.md) section B). That left the release with no audio
it was allowed to show. M7 closes that gap by synthesising the set from scratch.

Nothing in this set is a field recording and nothing here may be presented as one. Every upload carries
`device_info = {"source": "synthetic", "synthetic": true, "generator": "scripts/m7_synthetic_sounds.py", ...}`,
so a synthetic recording stays distinguishable from a real one for the life of the database.

## What exists

| File | Script |
|---|---|
| `scripts/m7_synthetic_sounds.py` | `generate`, `verify`, `probe`, `describe` |
| `scripts/m7_synthetic_journey.py` | the full journey, same assertions as `m55_real_journey.py`, synthetic audio |
| `server/data/m7_synthetic/` | generated WAVs, `manifest.json`, `clap-probe.json` (git-ignored, regenerate on demand) |
| `docs/integration-review/synthetic-journey.json` | the run report |

The audio itself is **not** committed; the generator is. It is seeded, so any clone reproduces byte-identical
files with `python scripts/m7_synthetic_sounds.py generate`. That is better than committing media: the repository
stays clean and the result stays reproducible.

## The set

Six clips, 10 s, 48 kHz mono, in two groups of three. The structure is what the journey's assertions need:

| File | Teach as | Role |
|---|---|---|
| `gutter-light.wav` | Roof gutter | taught exemplar 1 |
| `gutter-steady.wav` | Roof gutter | taught exemplar 2 |
| `gutter-windy.wav` | — | **held out**: the memory proof |
| `bells-distant.wav` | Bells | taught + composition source 1 |
| `bells-near.wav` | Bells | taught + composition source 2 |
| `bells-resonant.wav` | Bells | taught + composition source 3 |

Two gutter clips are taught a name the model has never heard; the third is never taught. Its ranking before and
after teaching is the only thing that demonstrates personalised retrieval memory. The three bells give the
Composed renderer the three taught sources it requires.

## Synthesis

Not sample-based. The gutter is 1/f noise band-passed to 600 Hz - 11 kHz with a slow gust modulation, plus
Poisson-distributed droplet onsets, each a short damped sinusoid at a randomised multiple of the gutter's metal
resonance, convolved with a small synthetic room. The bell is modal: the partial ratios of a tuned bell (hum 0.5,
prime 1.0, tierce 1.1892, quint 1.5, nominal 2.0 and two upper partials), each with its own decay time so high
partials die first, each doubled at a slight detune so the tail beats, struck with a short band-passed noise burst
and placed in a longer room.

Every clip is normalised to -22 dBFS RMS with the peak capped at 0.89 and DC removed, which clears every ingest
threshold with margin (reject below -60 dBFS, "quiet" flag below -40, clipping at 0.99).

## Droplet density is what decides whether CLAP hears rain

The first version used sparse droplets (14-34 per second). CLAP heard **wind chimes**, because sparse pitched
rings are what a wind chime is. The taught label then landed at **rank 4** on the held-out clip even though memory
similarity was 0.947 - the base distribution was too confident about three competitors.

Fusion is `log f(c) = (1-λ)·log s_base(c) + λ·log s_mem(c)` with `λ = n_rel/(n_rel+κ)`, so with two exemplars
λ = 0.4 and 60 % of the weight stays on the base score. Base scores are a softmax over cosines at `t_base = 0.05`,
which is sharp: what matters is the *gap* between competitors, not the absolute cosine.

Raising density to 150-380 droplets per second fixed it at the source rather than by weakening the assertion:

| Density | Held-out rank | cos(x, "The sound of Roof gutter.") | CLAP's top labels |
|---|---|---|---|
| 26/s | 4 | +0.2145 | Wind chimes, Rustling leaves, Rain |
| 120/s | 3 | +0.1473 | Wind chimes, Rain, Roof gutter |
| **300/s** | **1** | +0.1411 | **Roof gutter, Rain, Wind chimes** |
| 800/s | 2 | +0.1055 | Rain, Roof gutter, Train |
| 1500/s | 8 | +0.0712 | Wind, Rain, Rustling leaves |

The text cosine *fell* while the rank *rose*. Dense rain flattens the base distribution, which lets the memory
term carry the taught label; past about 800/s the signal turns into undifferentiated wind and the rank collapses.

## Measured with real CLAP

`laion/clap-htsat-unfused`, CPU, offline cache, 512 dimensions.

Zero-shot, after tuning: all three gutter clips rank **Rain** first; all three bells rank **Music** first, with
"Church bells" and "a gong" close behind. CLAP mistaking a bell for music is not a defect here - it is the
premise. ECHO-0 cannot name your sound; you teach it.

Group separation on pooled embeddings:

| Measure | Value |
|---|---|
| intra-group mean cosine | +0.9206 (n=6) |
| inter-group mean cosine | +0.0518 (n=9) |
| separation | +0.8688 |
| held-out vs its two taught clips | +0.9473, +0.8959 |
| held-out vs nearest other-group clip | +0.0655 |

**Caveat, stated in `clap-probe.json` as well.** Variants inside a group share one synthesis algorithm and differ
only by parameters, so they are more self-similar than genuinely different field recordings of the same source.
The ESC-50 measurement of the same mechanism gave a held-out similarity of 0.837261; this set gives 0.947. This is
therefore an **easier case**, and the result should be reported as a working demonstration of the mechanism, not
as evidence of field performance.

## Journey result

Fresh disposable profile, real CLAP on CPU, `UNHEARD_DATA_DIR=/tmp/unheard-m7`, port 8011.

| Step | Result |
|---|---|
| 6 uploads | accepted, no quality flags, 404-420 ms to ready, 2-810 ms to inference |
| CLAP first impressions | gutter -> Rain; bells -> Music |
| Held-out before teaching | Rain, Wind chimes, Rustling leaves ("Roof gutter" absent) |
| Held-out after teaching two | **Roof gutter, Rain, Wind chimes** - rank 1, 2 exemplars, memory similarity 0.965, fused 0.2128, evidence `memory` |
| Mission | "Something unlike the rest" offered and activated |
| Composed render, 3 sources, seed 55, 24 s | ready in 1215 ms and 2016 ms on two runs |
| Narrative | settled via **template fallback** (see below) |
| State | `phase: remembered`, `ending_unlocked: true` |
| Atlas | 6 nodes |
| Total | 9.4 s and 10.8 s on two runs |

Narration fell back to the deterministic template because `gemma3:4b` was not installed on the machine that ran
this; Ollama reported `unavailable` with it stopped and `no_model` with it running. That is a property of the run,
not of the pipeline - M6 validated real Gemma
separately with `gemma3:4b`. A run with Gemma present should report its own statistics and must not reuse M6's
figures.

The journey was run twice on independent fresh profiles and gave the same rank, the same top-3 ordering and the
same exemplar count, which is what "deterministic" is supposed to mean here.

## Reproducing

```bash
python scripts/m7_synthetic_sounds.py generate
python scripts/m7_synthetic_sounds.py verify                       # backend's own sniffer + decoder + validator
HF_HUB_OFFLINE=1 uv run --extra ml python ../scripts/m7_synthetic_sounds.py probe   # from server/

rm -rf /tmp/unheard-m7
UNHEARD_DATA_DIR=/tmp/unheard-m7 HF_HUB_OFFLINE=1 uv run --extra ml unheard serve --port 8011
UNHEARD_REVIEW_URL=http://127.0.0.1:8011 python scripts/m7_synthetic_journey.py
```

## What may and may not be claimed

| You may say | You may not say |
|---|---|
| The demo audio is synthesised by a script in this repository and is free to publish | that these are field recordings, or that they were recorded outdoors |
| Teaching two clips a new name moved it to rank 1 on a held-out clip of the same synthetic source | that this measures performance on real-world audio |
| CLAP, personalised memory and narration are three separate mechanisms | that the model was retrained or fine-tuned |
| ESC-50 remains private evaluation material and is not shipped | anything about Gemma from this run beyond `unavailable` |
