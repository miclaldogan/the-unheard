<!-- Proposed root-README addition for M5. NOT applied: the root README is edited by one agent at a time. -->

### ECHO-0, the narrator (M5)

ECHO-0 speaks through a local Gemma model (default `gemma3:4b` via [Ollama](https://ollama.com)). Gemma only words
things: the story state, missions and their completion are computed from your own data, every line is checked against the
facts it cites, and anything that fails is replaced by a fixed template. Nothing leaves your machine. Without Ollama the
game works exactly the same with template lines.

```bash
ollama pull gemma3:4b      # optional, ~3.3 GB
cd server && uv run unheard serve
```

Details: [`docs/gemma-narrative-engine.md`](docs/gemma-narrative-engine.md), results and limits:
[`docs/M5-REPORT.md`](docs/M5-REPORT.md).
