# Visual review — THE UNHEARD

Chrome 148, browser sandbox enabled; real FastAPI responses, DSP artifacts, annotations and composition renders. Audio was captured from Chrome's simulated microphone, with CLAP and Gemma disabled. The M5 voice is the backend's grounded template implementation. These are human-review artifacts, not production fixtures. No player audio is committed.

| Image | What to inspect |
| --- | --- |
| [01 Chamber](01-chamber-desktop.png) | Empty-memory entrance at 1440 × 1000 |
| [02 Field ready](02-field-ready-mobile.png) | Portrait 390 × 844 hierarchy and record control |
| [03 Recording](03-field-recording-mobile.png) | Explicit live state and locked navigation |
| [04 Local save / failed upload](04-field-offline-saved-mobile.png) | Truthful storage and recoverable error |
| [05 Hearing](05-hearing-laptop.png) | Actual annotation, waveform/spectrogram and source provenance at 1366 × 900 |
| [06 Specimen](06-specimen-laptop.png) | Actual measured acoustic geometry and original playback |
| [07 Atlas](07-atlas-laptop.png) | Real nodes, accessible selection and zoom |
| [08 Organic](08-orchestra-organic-laptop.png) | Real event plan, transport and source layer |
| [09 Composed](09-orchestra-composed-laptop.png) | Three actual taught sources and composed arrangement |
| [10 Landscape](10-field-landscape.png) | 844 × 390 Field layout |
| [11 Production offline](11-pwa-offline-mobile.png) | Installed shell loaded and captured while disconnected |
| [12 Remembered Chamber](12-chamber-remembered-desktop.png) | Backend ending and actual completed acts |

`browser-results.json` records the interaction walkthrough, `pwa-results.json` records the production shell/auth/cache checks, `narrative-review.json` records actual ending/mission activation and the atlas draw measurement, and `storage-results.json` records the IndexedDB count-bound/recovery check. Figures are small-library desktop measurements, not phone or stress benchmarks. Follow `../UI-MANUAL-TEST-CHECKLIST.md` for physical-device and artistic review.
