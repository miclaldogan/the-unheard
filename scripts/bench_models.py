#!/usr/bin/env python3
"""Benchmark the CLAP adapter on real ESC-50 clips (doc 03 M0 gate, run in M2).

Usage: cd server && uv run python ../scripts/bench_models.py [--clips N] [--device cpu]
Reports: load time, RSS before/after, cold/warm latency per 5 s clip, embedding dim,
zero-shot top-1/top-3 against the project vocabulary on the downloaded ESC-50 subset.
"""

from __future__ import annotations

import argparse
import csv
import json
import resource
import sys
import time
from pathlib import Path

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
from unheard.models.clap import ClapAudioModel  # noqa: E402
from unheard.models.vocabulary import VOCABULARY, prompt_for  # noqa: E402

# ESC-50 category → vocabulary slug (what a correct zero-shot answer looks like)
ESC_TO_SLUG = {"rain": "rain", "chirping_birds": "birds", "engine": "car_engine", "footsteps": "footsteps",
               "wind": "wind", "church_bells": "church_bells"}


def rss_mb() -> float:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--clips", type=int, default=240)
    ap.add_argument("--esc", default=str(Path(__file__).resolve().parents[1] / "server/data/eval/esc50"))
    args = ap.parse_args()
    esc = Path(args.esc)
    rows = [r for r in csv.DictReader(open(esc / "esc50.csv")) if r["category"] in ESC_TO_SLUG and (esc / r["filename"]).exists()]
    rows = rows[: args.clips]
    print(f"clips available: {len(rows)}")

    print(f"rss before load: {rss_mb():.0f} MB")
    m = ClapAudioModel(device=args.device, allow_download=False)
    m.load()
    print(f"load: {m.load_seconds:.1f} s, rss after load: {rss_mb():.0f} MB, dim={m.embedding_dim}, revision={m.revision}")
    try:
        import torch
        if args.device != "cpu":
            print(f"vram: {torch.cuda.max_memory_allocated() / 2**20:.0f} MB")
    except Exception:  # noqa: BLE001
        pass

    t = time.perf_counter()
    text = m.embed_text([prompt_for(p) for _, _, p in VOCABULARY])
    print(f"text embeddings for {len(VOCABULARY)} labels: {(time.perf_counter() - t) * 1000:.0f} ms")
    slugs = [s for s, _, _ in VOCABULARY]

    lat: list[float] = []
    top1 = top3 = 0
    per_class: dict[str, list[int]] = {}
    embs = []
    cold = None
    for i, r in enumerate(rows):
        x, sr = sf.read(esc / r["filename"], dtype="float32")
        if x.ndim > 1:
            x = x.mean(axis=1)
        t = time.perf_counter()
        w = m.embed_windows(x, sr)
        dt = time.perf_counter() - t
        if cold is None:
            cold = dt
        else:
            lat.append(dt)
        v = w[0].vec
        embs.append((r["category"], r["fold"], v))
        sims = text @ v
        order = np.argsort(-sims)
        want = ESC_TO_SLUG[r["category"]]
        hit1 = slugs[order[0]] == want
        hit3 = want in [slugs[j] for j in order[:3]]
        top1 += hit1
        top3 += hit3
        per_class.setdefault(r["category"], []).append(int(hit1))
        if i < 6:
            print(f"  {r['filename']}: {r['category']:>15} → {[ (slugs[j], round(float(sims[j]),3)) for j in order[:3]]}")
    n = len(rows)
    print(f"cold inference (first 5 s clip incl. 44.1k→48k resample): {cold * 1000:.0f} ms")
    print(f"warm inference per 5 s clip: p50 {np.median(lat) * 1000:.0f} ms, p95 {np.percentile(lat, 95) * 1000:.0f} ms, mean {np.mean(lat) * 1000:.0f} ms")
    print(f"rss peak: {rss_mb():.0f} MB")
    print(f"zero-shot (vocabulary of {len(slugs)} labels) on {n} ESC-50 clips: top-1 {top1 / n:.3f}, top-3 {top3 / n:.3f}")
    for c, hits in sorted(per_class.items()):
        print(f"  {c:>15}: top-1 {np.mean(hits):.2f} (n={len(hits)})")
    # kNN recall@5 (same-class neighbours among the 5 nearest, leave-one-out, across folds)
    V = np.stack([e[2] for e in embs])
    cats = [e[0] for e in embs]
    S = V @ V.T
    np.fill_diagonal(S, -1)
    rec = []
    same_class_cos, diff_class_cos = [], []
    for i in range(len(embs)):
        nn = np.argsort(-S[i])[:5]
        rec.append(np.mean([cats[j] == cats[i] for j in nn]))
        for j in range(len(embs)):
            if j == i:
                continue
            (same_class_cos if cats[j] == cats[i] else diff_class_cos).append(S[i, j])
    print(f"embedding kNN recall@5 (leave-one-out): {np.mean(rec):.3f}")
    print(f"audio-audio cosine: same class median {np.median(same_class_cos):.3f} (p10 {np.percentile(same_class_cos,10):.3f}), "
          f"different class median {np.median(diff_class_cos):.3f} (p90 {np.percentile(diff_class_cos,90):.3f})")
    nn1 = [float(np.max(S[i])) for i in range(len(embs))]
    print(f"nearest-neighbour cosine: p5 {np.percentile(nn1,5):.3f}, median {np.median(nn1):.3f}")
    json.dump({"n": n, "top1": top1 / n, "top3": top3 / n, "load_s": m.load_seconds, "cold_ms": cold * 1000,
               "warm_p50_ms": float(np.median(lat) * 1000), "rss_mb": rss_mb(), "dim": m.embedding_dim,
               "revision": m.revision, "knn_recall5": float(np.mean(rec))},
              open(esc.parent / "bench_clap.json", "w"), indent=2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
