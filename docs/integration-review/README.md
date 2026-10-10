# Integrated-system review artifacts

Captured October 10, 2026 in sandboxed Chrome 148. Desktop 1440×1000, laptop 1366×900,
portrait 390×844 and landscape 844×390. Backend and DSP/music/state are real.
Most automation uses explicit simulated microphone input; `hardware-microphone-recording.png` and
`hardware-microphone.json` document the separate **actual laptop microphone** capture. No physical Android/outdoor test.

| Artifact | Review focus |
| --- | --- |
| `01-prologue.png` | Fresh empty profile, immediate grounded invitation |
| `hardware-microphone-recording.png` | Visible recording with a real laptop input |
| `05-hearing-laptop.png` | Real predictions, annotation and acoustic memory |
| `06-specimen-laptop.png` | Measured signature and original playback |
| `07-atlas-laptop.png` | Actual CLAP-derived memory graph |
| `09-orchestra-composed-laptop.png` | Real composed render, sources and controls |
| `11-pwa-offline-mobile.png` | Production shell reloaded offline and saved a capture locally |
| `12-ending-provenance.png` | Backend-earned ending and its facts |
| `13-gemma-pending.png` / `14-gemma-settled.png` | Immediate template → actual Gemma after pending reload |
| `16-gemma-unavailable.png` | Real unavailable-runtime fallback |

JSON files preserve actual observations, ephemeral QA identifiers and factual metrics, never audio or databases.
`real-model-journey.json`: six real local ESC-50 clips, real CPU inference and held-out personalization, composition,
mission activation and ending. Evaluation audio stays private/local; it is not cleared demo audio.
`pending-browser.json` uses a fresh profile with CLAP disabled only for that isolated narration timing check.
`pwa-results.json` covers authenticated offline behavior with CLAP disabled for the initial PWA check.
The final browser and PWA reruns use real CLAP/Gemma; their `final-*` results identify that distinction.
`recovery-results.json`: unavailable model/runtime, actual failed render from a temporarily withheld disposable canonical
asset, restored source/retry and raw preservation. `restart-recovery.json` verifies persisted records and successful
real inference after restart; annotations taught before hearing need resubmission to create acoustic exemplars.
`lost-response.json`: server accepted upload, browser lost acknowledgement, retry created no duplicate.

These artifacts demonstrate function and rendered appearance. Human emotional/musical/prose judgments remain unscored.
