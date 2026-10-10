# THE UNHEARD — art direction

An engraved acoustic observatory: dark optical surfaces, aged copper index marks, an ivory editorial voice, and teal light where memory becomes legible. The aesthetic is a quiet scientific exhibition, not a terminal or statistics dashboard.

## Tokens

| Purpose | Token / value |
| --- | --- |
| Ground | `--ground: #101213` (development of graphite #121315) |
| Instrument surface | `--ground-2: #181b1b` |
| Raised controls | `--ground-3: #202626` |
| Structural borders | `--line: #343a37` |
| Main text | `--text: #e7e3da` |
| Secondary text | `--text-dim: #b0b2a6` |
| Copper / action | `--copper: #cc925b` (lighter for readability) |
| Muted amber | `--amber: #d9a441` |
| Acoustic teal / confirmed memory | `--teal: #70c5ba` |
| Danger | `--danger: #c0564a`, accompanied by text |

System serif faces (`Iowan Old Style`, Palatino, Book Antiqua, Georgia) carry narrative and scene titles. The operating system sans-serif carries controls; UI monospace carries indices and measurements. No downloaded font files or font-CDN requests are needed. Appearance can vary slightly across systems; readability has priority over exact font matching.

The Chamber uses generous asymmetry: the player's invitation on the left, the identity instrument on the right. Fine reference circles and engraved corner marks surround the ECHO-0 core. The core's dots summarize actual preserved signals, capped at 24 for visual restraint; they are not specimen measurements or narrative progress. Actual acts are a separate, backend-derived sequence.

Hearing balances a physical capture instrument with a conversation and measured evidence. Specimen uses an optical frame around the unchanged mathematical artifact. Atlas keeps a dark canvas and the original stable coordinates; accessible selection controls sit outside the canvas. Orchestra retains a legible event score, copper source selection and real-time instrument activity rather than decorative particles.

## Motion grammar

A short 400 ms Chamber entry establishes arrival. Dormant instruments are still; remembering/listening cores breathe through opacity on a five-second cycle. Learning uses a short connection transition. The annotation-formation acknowledgement appears only after a successful backend response. Specimen and orchestra motion remain bound to real audio envelopes/events. No extra UI audio or animation library was introduced. Reduced motion disables presentation animation and retains meaningful static states.

## Asset provenance

All added atmospheric artwork is code-native CSS/SVG. The grain texture and `web/public/icon.svg` were already in the baseline repository. The 192 and 512 px PNG installation icons are raster exports of that existing SVG. No generated AI illustrations, third-party stock images or redistributed font files were added. Screenshot artifacts contain browser test audio rendered by the real DSP backend; they are review documentation, not app assets or recordings shipped to players.

## Visual quality review

The screenshot set in `ui-review/` shows the entrance, field states, measured specimen, atlas and both orchestra modes at desktop/laptop/portrait/landscape sizes. Identity is carried by typography, proportion and the instrument motif. Narrative progression was checked against real M5 responses. Original score semantics and mathematical signatures are retained. Technical checks cannot validate emotional impact or actual outdoor readability: those remain part of the human review in `UI-MANUAL-TEST-CHECKLIST.md`.
