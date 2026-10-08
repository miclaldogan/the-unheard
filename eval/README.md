# Evaluation

`run_eval.py` measures whether personal memory improves held-out recognition, using the
ESC-50 subset downloaded to `server/data/eval/esc50/` (6 classes: rain, chirping_birds,
engine, footsteps, wind, church_bells; CC BY-NC 3.0, local evaluation only, not redistributed).

```bash
cd server && uv run python ../eval/run_eval.py          # writes eval/reports/esc50_personalization.{json,md}
```

Protocol: ESC-50 folds group clips by their Freesound source recording, so splitting by fold
keeps near-duplicate takes of one source on the same side. For every test fold, memory
exemplars are sampled (seeded) from the *other* folds with n ∈ {0, 1, 3, 5} per class, the
fused prediction (same code path as the server) is computed for each test clip, and
top-1 / top-3 / macro-F1 / per-class P/R are averaged across the 5 folds. "wind" is also
held out of memory entirely to measure unknown handling. n = 0 is the base model alone.
