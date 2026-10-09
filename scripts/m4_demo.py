"""Render the three M4 demonstration compositions from real ESC-50 clips.

ESC-50 (CC BY-NC 3.0) is a local evaluation dataset: the clips and the rendered WAVs stay
under ``server/data/`` (git-ignored) and are never redistributed. Usage::

    cd server && uv run python ../scripts/m4_demo.py [--out data/m4_demo] [--seed 7]
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
import time
from pathlib import Path

import numpy as np
import soundfile as sf

from unheard.dsp.features import extract_features
from unheard.music.engine import SourceInput, compose
from unheard.music.render import SR, to_pcm16

ROOT = Path(__file__).resolve().parents[1]
ESC = ROOT / "server" / "data" / "eval" / "esc50"

SETS = {
    "A_natural": ["1-12653-A-15.wav", "1-34495-A-14.wav", "1-137296-A-16.wav", "1-17367-A-10.wav"],
    "B_urban": ["1-155858-A-25.wav", "1-22882-A-44.wav", "1-24074-A-43.wav", "1-21935-A-38.wav"],
    "C_hybrid": ["1-17367-A-10.wav", "1-13572-A-46.wav", "1-155858-A-25.wav", "1-19840-A-36.wav"],
}


def load_clip(name: str) -> SourceInput:
    raw = subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-i",
            str(ESC / name),
            "-ac",
            "1",
            "-ar",
            str(SR),
            "-f",
            "f32le",
            "-",
        ],
        capture_output=True,
        check=True,
    ).stdout
    x = np.frombuffer(raw, dtype="<f4").astype(np.float64)
    nz = np.where(np.abs(x) > 1e-4)[0]
    x = x[: nz[-1] + 1] if nz.size else x  # ESC-50 pads short clips with digital silence
    key = hashlib.sha256(x.astype("<f4").tobytes()).hexdigest()
    return SourceInput(key, x, extract_features(x, SR).arrays)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "server" / "data" / "m4_demo"))
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--duration", type=float, default=40.0)
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    rows = {r["filename"]: r["category"] for r in csv.DictReader(open(ESC / "esc50.csv"))}
    report = {}
    for name, files in SETS.items():
        srcs = [load_clip(f) for f in files]
        names = {s.key: f"{rows[f]} ({f})" for s, f in zip(srcs, files, strict=True)}
        t = time.perf_counter()
        res = compose(srcs, seed=args.seed, duration_s=args.duration)
        dt = time.perf_counter() - t
        sf.write(out / f"{name}_master.wav", to_pcm16(res.master), SR, subtype="PCM_16")
        for tid, stem in res.stems.items():
            sf.write(out / f"{name}_{tid}.wav", to_pcm16(stem), SR, subtype="PCM_16")
        (out / f"{name}_plan.json").write_text(json.dumps(res.plan, indent=1))
        report[name] = {
            "sources": {
                names[k]: {"role": d.primary, "secondary": d.secondary, "why": d.rationale}
                for k, d in res.roles.items()
            },
            "tempo_bpm": res.plan["tempo_bpm"],
            "tempo_source": res.plan["tempo_source"],
            "key": res.plan["key"],
            "sections": [(s["name"], s["bars"]) for s in res.plan["sections"]],
            "n_events": len(res.plan["events"]),
            "plan_hash": res.plan_hash[:12],
            "render_s": round(dt, 2),
            "metrics": {
                k: v
                for k, v in res.metrics.items()
                if k not in ("track_contribution", "section_rms")
            },
            "section_rms": res.metrics["section_rms"],
            "contribution": res.metrics["track_contribution"],
        }
        print(name, json.dumps(report[name], indent=1, default=str))
    (out / "report.json").write_text(json.dumps(report, indent=1, default=str))


if __name__ == "__main__":
    main()
