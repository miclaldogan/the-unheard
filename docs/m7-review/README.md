# M7 visual review — the app running on publishable audio

Thirteen frames of the six scenes at desktop and mobile widths, captured against a backend seeded entirely by the
synthetic set from [`scripts/m7_synthetic_sounds.py`](../../scripts/m7_synthetic_sounds.py). Unlike
[`../ui-review/`](../ui-review/), which used Chrome's fake microphone and a label typed by the script, every
recording here is a real 10 s signal, analysed by real CLAP, taught a real name, and composed into a real render.
Nothing is ESC-50, so these frames may be published.

Capture: `web/scripts/m7-shots.cjs`, Chrome 150 headless with the sandbox on, `deviceScaleFactor: 2` then
downscaled to 1x for the repository. Narration came from real `gemma3:4b` through Ollama.

**These are emulated viewports, not a physical phone.** `shots.json` records `physicalDevice: false`. The mobile
frames are 390 x 844 in desktop Chrome. Nothing here supports a claim that the app was tested on a phone or
outdoors, and the audio is synthesised, not recorded in the field.

| Frame | What to look at |
| --- | --- |
| [01 Chamber, desktop](01-chamber-desktop.png) · [02 mobile](02-chamber-mobile.png) | ECHO-0's entrance and its grounded voice |
| [03 Field, desktop](03-field-desktop.png) · [04 mobile](04-field-mobile.png) | the recorder, the active mission, the 64 MiB field notebook |
| [**05 Hearing, desktop**](05-hearing-desktop.png) · [06 mobile](06-hearing-mobile.png) | **the memory proof, below** |
| [07 Specimen, desktop](07-specimen-desktop.png) · [08 mobile](08-specimen-mobile.png) | the measured acoustic signature and its similar memories |
| [09 Atlas, desktop](09-atlas-desktop.png) · [10 mobile](10-atlas-mobile.png) | real embedding similarities, two labelled clusters |
| [11 Orchestra, desktop](11-orchestra-desktop.png) · [12 mobile](12-orchestra-mobile.png) | the Composed render, its layers, sections and transport |
| [13 Field, landscape](13-field-landscape.png) | 844 x 390 layout |
| [cover 1000 x 420](cover-1000x420.png) | the prediction table cropped to DEV's cover ratio |

## Frame 05 is the one that carries the project

The held-out clip was never taught. Its ranking in that frame reads:

| # | Source | Ears cosine | Memory nearest · n | Fused |
|---|---|---|---|---|
| 1 | **Roof gutter** `MEMORY` | 0.141 | **0.965 · 2** | 0.210 |
| 2 | Rain `EARS` | 0.320 | — | 0.169 |
| 3 | Wind chimes `EARS` | 0.299 | — | 0.131 |

CLAP's own ears rank **Rain above Roof gutter** (0.320 against 0.141). The taught name still comes first, because
two remembered exemplars sit at cosine 0.965. That single table is the whole argument: retrieval memory
overturning the model's first impression, with both numbers visible and neither presented as a probability.

The same frame carries the DSP panel (10.00 s, RMS -22.1 dBFS, peak -6.6 dBFS, centroid 2815 Hz, 14 onsets),
the waveform, the log-mel spectrogram, and a similar-memories list where the two taught gutter clips sit at
0.965 and 0.893 while every bell sits near -0.02.

## State behind the frames

6 recordings, 6 heard, 6 taught, 2 confirmed labels, 2 corrections, 2 compositions, memory version 6, phase
`remembered`, ending unlocked, 6 atlas nodes, no page errors. Gemma: 2 requests, 1 valid, 1 fallback
(`invalid_output`), cold first 9155 ms, p50 2946 ms — far too few calls to be a rate, and not comparable to the
M5 figure of 84.2 % over 57 calls.

Full records: [`shots.json`](shots.json) for the capture, [`journey.json`](journey.json) for the seeding run.

## Reproducing

```bash
python scripts/m7_synthetic_sounds.py generate
cd web && npm run build && cd ..
rm -rf /tmp/unheard-shots
UNHEARD_DATA_DIR=/tmp/unheard-shots UNHEARD_NARRATIVE_MODEL=gemma3:4b \
  uv run --extra ml unheard serve --port 8014            # from server/
UNHEARD_REVIEW_URL=http://127.0.0.1:8014 UNHEARD_REVIEW_DIR=/tmp/unheard-shots \
  python scripts/m7_synthetic_journey.py
UNHEARD_REVIEW_URL=http://127.0.0.1:8014 UNHEARD_SHOT_DIR=/tmp/unheard-shots/png \
  UNHEARD_HELD_ID=<held-out id from the journey report> \
  CHROME_PATH=/usr/bin/google-chrome-stable node web/scripts/m7-shots.cjs
```

`playwright-core` is not a dependency of this repository; install it anywhere and point `PLAYWRIGHT_MODULE` at it.
