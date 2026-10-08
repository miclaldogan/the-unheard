# 00 — Executive Vision

**THE UNHEARD** — *An orchestra made of a world you almost forgot to hear.*

ECHO-0 knows what a river is but has never heard one. The player goes outside, records real sound with a phone, and teaches ECHO-0. Every correction changes persistent state: a retrieval memory, an atlas, a visual artifact, and a musical composition built from the player's own recordings.

## One loop, not four features

`EXPLORE → RECORD → ANALYZE → QUESTION → LABEL → LEARN → REMEMBER → VISUALIZE → COMPOSE → EXPLORE`

| Concept | Technical mechanism (all real) |
|---|---|
| Silence Experiment | Recording-quality assessment + noise-floor/spectral display of the user's own surroundings |
| Listening Machine | Open-weight audio embedding model + kNN/prototype memory + human-in-the-loop labels |
| Frequencies of the Dead | Archive "fragments" = the user's recordings, revealed through STFT/onset/pitch analysis |
| Unheard Symphony | Deterministic sample-based renderer driven by measured onsets, spectra, energy |

## Why open matters (for the DEV post)
- Raw audio never leaves the machine: local inference, local SQLite.
- Models are swappable behind one adapter interface (`AudioModel`).
- The learning mechanism (retrieval memory) is inspectable; users can read why ECHO-0 guessed what it did.
- Costs nothing to run; no API keys.

## Honesty rules (non-negotiable)
1. "ECHO-0 learned" is only displayed after a `MemoryUpdated` event row exists.
2. The foundation model is **never fine-tuned** in the MVP. Only retrieval memory changes. UI and docs say "remembers", never "retrained".
3. Unknown ≠ guess. Low confidence is shown as uncertainty.
4. Generated visuals are depictions of measurements, not photos of sources.
5. ECHO-0 prose is interpretation; structured data is stored separately.

## Status of this document set
Architecture phase only. **No model was downloaded, no benchmark run.** Anything not measured is labelled `ESTIMATE`, `HYPOTHESIS`, or `VERIFY` and has a measurement procedure in [03](03-AUDIO-ML-RESEARCH.md) and [11](11-TESTING-AND-EVALUATION.md).
