# ruff: noqa: E501
"""M4.6: render each demo set in LEGACY (M4.5), ORGANIC and COMPOSED mode from the same recordings
and seed, loudness-match the A/B excerpts, and write objective diagnostics.

    cd server && uv run python ../scripts/m4_6_compare.py [--out data/m4_6] [--seed 7] [--duration 40]

Inputs are real ESC-50 clips (CC BY-NC 3.0, local evaluation only; never redistributed). Outputs stay
under the git-ignored ``server/data``. Comparison caveats are written into ``report.json``: the same
sources and seed are used, but each mode makes its own plan (different tempo, form and length), so
the excerpts are matched in loudness (integrated, K-weighted, -20 LUFS) and length, not in content.
"""

from __future__ import annotations

import argparse
import gc
import json
import time
from pathlib import Path

import numpy as np
import soundfile as sf
from m4_demo import SETS, load_clip

from unheard.music.engine import compose
from unheard.music.quality import evaluate
from unheard.music.render import SR, limiter_gain, loudness_lufs, to_pcm16

ROOT = Path(__file__).resolve().parents[1]
MODES = ("legacy", "organic", "composed")
# a rhythm-led urban set (no pitched source) used for the groove comparison
GROOVE_SET = ["1-155858-A-25.wav", "1-21935-A-38.wav", "1-22882-A-44.wav", "1-17367-A-10.wav"]
GROOVES = {"source_timed": 0.0, "hybrid": None, "quantized": 1.0}
AB_LUFS = -20.0
AB_SECONDS = 25.0


def excerpt(master: np.ndarray, plan: dict) -> np.ndarray:  # type: ignore[type-arg]
    conv = next(s for s in plan["sections"] if s["name"] == "convergence")
    a = max(0.0, conv["start_s"] - 8.0)
    i0 = int(a * SR)
    i1 = min(master.shape[0], i0 + int(AB_SECONDS * SR))
    ex = master[i0:i1].copy()
    fade = int(0.05 * SR)
    ex[:fade] *= np.linspace(0, 1, fade)[:, None]
    ex[-fade:] *= np.linspace(1, 0, fade)[:, None]
    return ex


def loudness_match(ex: np.ndarray) -> tuple[np.ndarray, float, float]:
    before = loudness_lufs(ex)
    g = 10 ** ((AB_LUFS - before) / 20)
    out = ex * g
    out = out * limiter_gain(out)[:, None]
    return out, before, loudness_lufs(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "server" / "data" / "m4_6"))
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--duration", type=float, default=40.0)
    a = ap.parse_args()
    out = Path(a.out)
    (out / "AB").mkdir(parents=True, exist_ok=True)
    report: dict = {  # type: ignore[type-arg]
        "seed": a.seed,
        "target_duration_s": a.duration,
        "ab_loudness_target_lufs": AB_LUFS,
        "caveats": [
            "same recordings and seed for every mode, but each planner makes its own plan (tempo, form, length differ)",
            "A/B excerpts are the convergence section (+8 s lead-in), 25 s, matched to the same integrated loudness",
            "objective metrics only; no human has listened",
        ],
        "sets": {},
    }
    for name, files in SETS.items():
        srcs = [load_clip(f) for f in files]
        report["sets"][name] = {}
        for mode in MODES:
            t0 = time.perf_counter()
            res = compose(srcs, seed=a.seed, duration_s=a.duration, mode=mode)
            dt = time.perf_counter() - t0
            d = out / name / mode
            d.mkdir(parents=True, exist_ok=True)
            sf.write(d / "master.wav", to_pcm16(res.master), SR, subtype="PCM_16")
            for tid, stem in res.stems.items():
                sf.write(d / f"stem_{tid}.wav", to_pcm16(stem), SR, subtype="PCM_16")
            (d / "plan.json").write_text(json.dumps(res.plan, indent=1))
            ex = excerpt(res.master, res.plan)
            matched, before, after = loudness_match(ex)
            sf.write(out / "AB" / f"{name}_{mode}.wav", to_pcm16(matched), SR, subtype="PCM_16")
            q = evaluate(res.plan, res.stems, res.master)
            report["sets"][name][mode] = {
                "render_and_plan_s": round(dt, 2),
                "duration_s": round(res.plan["duration_s"], 2),
                "tempo_bpm": res.plan["tempo_bpm"],
                "events": len(res.plan["events"]),
                "plan_hash": res.plan_hash[:12],
                "master_lufs": round(res.metrics["lufs_approx"], 1),
                "master_peak_dbfs": round(res.metrics["peak_dbfs"], 2),
                "excerpt_lufs_before": round(before, 1),
                "excerpt_lufs_after": round(after, 1),
                "excerpt_peak_dbfs": round(float(20 * np.log10(np.abs(matched).max())), 2),
                "tracks": [
                    (t["id"], t.get("hierarchy", t["role"]), t["role"]) for t in res.plan["tracks"]
                ],
                "quality": q,
            }
            n_events, lufs_m = len(res.plan["events"]), res.metrics["lufs_approx"]
            del res, ex, matched
            gc.collect()
            print(
                f"{name:10s} {mode:9s} events={n_events:4d} lufs={lufs_m:.1f} "
                f"excerpt {before:.1f}->{after:.1f} flags={len(q['flags'])} t={dt:.1f}s"
            )
    srcs = [load_clip(f) for f in GROOVE_SET]
    report["groove_comparison"] = {}
    for gname, gq in GROOVES.items():
        res = compose(srcs, seed=a.seed, duration_s=a.duration, mode="composed", groove_q=gq)
        d = out / "groove" / gname
        d.mkdir(parents=True, exist_ok=True)
        ex = excerpt(res.master, res.plan)
        matched, before, after = loudness_match(ex)
        sf.write(
            out / "AB" / f"B2_urban_rhythm_groove_{gname}.wav",
            to_pcm16(matched),
            SR,
            subtype="PCM_16",
        )
        q = evaluate(res.plan, res.stems, res.master)
        report["groove_comparison"][gname] = {
            "quantisation": res.plan["groove"]["quantisation"],
            "lead_kind": res.plan["hierarchy"]["lead_kind"],
            "excerpt_lufs_after": round(after, 1),
            "rhythm": q["measured"]["rhythm"],
            "flags": q["flags"],
        }
        print(
            f"groove {gname:13s} lead={res.plan['hierarchy']['lead_kind']} off_grid={q['measured']['rhythm']['off_grid_share']}"
        )
        del res, ex, matched
        gc.collect()
    (out / "report.json").write_text(json.dumps(report, indent=1, default=str))
    print("wrote", out / "report.json")


if __name__ == "__main__":
    main()
