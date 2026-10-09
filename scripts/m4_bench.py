"""M4 benchmarks: planning time, rendering time, peak RSS, file size.

Real ESC-50 clips only (see m4_demo.py). Each configuration runs in a fresh subprocess so the
peak RSS (``ru_maxrss``) is attributable to that configuration alone.

    cd server && uv run python ../scripts/m4_bench.py
"""

from __future__ import annotations

import json
import platform
import resource
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ESC = ROOT / "server" / "data" / "eval" / "esc50"
CLIPS = [
    "1-12653-A-15.wav",
    "1-34495-A-14.wav",
    "1-137296-A-16.wav",
    "1-17367-A-10.wav",
    "1-155858-A-25.wav",
    "1-22882-A-44.wav",
    "1-24074-A-43.wav",
    "1-21935-A-38.wav",
]
CONFIGS = [(3, 30), (5, 60), (8, 60)]


def child(n: int, dur: int) -> None:
    sys.path.insert(0, str(Path(__file__).parent))
    from m4_demo import load_clip

    from unheard.music.engine import analyse_and_plan
    from unheard.music.planner import canonical_plan_hash
    from unheard.music.render import render_plan, to_pcm16

    srcs = [load_clip(f) for f in CLIPS[:n]]
    t0 = time.perf_counter()
    plan, _, _ = analyse_and_plan(srcs, seed=7, duration_s=dur)
    t_plan = time.perf_counter() - t0
    t1 = time.perf_counter()
    _, master, metrics = render_plan(plan, {s.key: s.samples for s in srcs})
    t_render = time.perf_counter() - t1
    size = to_pcm16(master).nbytes + 44
    print(
        json.dumps(
            {
                "sources": n,
                "target_s": dur,
                "piece_s": round(plan["duration_s"], 1),
                "events": len(plan["events"]),
                "analysis_plus_plan_s": round(t_plan, 2),
                "render_s": round(t_render, 2),
                "render_x_realtime": round(t_render / metrics["duration_s"], 3),
                "peak_rss_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024),
                "master_wav_mb": round(size / 1e6, 2),
                "lufs": round(metrics["lufs_approx"], 1),
                "plan_hash": canonical_plan_hash(plan)[:10],
            }
        )
    )


def main() -> None:
    if len(sys.argv) == 3:
        child(int(sys.argv[1]), int(sys.argv[2]))
        return
    assert (ESC / "esc50.csv").exists(), "download ESC-50 clips first (see eval/README.md)"
    print(f"# {platform.platform()} · python {platform.python_version()}")
    for n, d in CONFIGS:
        out = subprocess.run(
            [sys.executable, __file__, str(n), str(d)], capture_output=True, text=True, check=True
        )
        print(out.stdout.strip())


if __name__ == "__main__":
    main()
