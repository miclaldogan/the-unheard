#!/usr/bin/env python3
"""Before/after personalization on ESC-50 (held-out by fold). See eval/README.md."""

from __future__ import annotations

import csv
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))
from unheard.memory.engine import FusionParams, MemoryIndex, fuse  # noqa: E402
from unheard.models.clap import ClapAudioModel  # noqa: E402
from unheard.models.vocabulary import VOCABULARY, prompt_for  # noqa: E402

ESC = ROOT / "server" / "data" / "eval" / "esc50"
CACHE = ROOT / "server" / "data" / "eval" / "esc50_clap_embeddings.npz"
OUT = ROOT / "eval" / "reports"
ESC_TO_SLUG = {"rain": "rain", "chirping_birds": "birds", "engine": "car_engine", "footsteps": "footsteps",
               "wind": "wind", "church_bells": "church_bells"}
UNKNOWN_CLASS = "wind"
NS = [0, 1, 3, 5]
SEEDS = [0, 1, 2]


def embed_all() -> tuple[list[dict], np.ndarray, np.ndarray, list[str]]:
    rows = [r for r in csv.DictReader(open(ESC / "esc50.csv")) if r["category"] in ESC_TO_SLUG and (ESC / r["filename"]).exists()]
    slugs = [s for s, _, _ in VOCABULARY]
    if CACHE.exists():
        z = np.load(CACHE, allow_pickle=False)
        names = list(z["filenames"])
        if names == [r["filename"] for r in rows]:
            return rows, z["audio"], z["text"], slugs
    m = ClapAudioModel()
    m.load()
    text = m.embed_text([prompt_for(p) for _, _, p in VOCABULARY])
    audio = np.zeros((len(rows), m.embedding_dim), np.float32)
    t0 = time.perf_counter()
    for i, r in enumerate(rows):
        x, sr = sf.read(ESC / r["filename"], dtype="float32")
        if x.ndim > 1:
            x = x.mean(axis=1)
        audio[i] = m.embed_windows(x, sr)[0].vec
    print(f"embedded {len(rows)} clips in {time.perf_counter() - t0:.1f} s", file=sys.stderr)
    np.savez(CACHE, filenames=np.array([r["filename"] for r in rows]), audio=audio, text=text)
    return rows, audio, text, slugs


def metrics(y_true: list[str], y_pred: list[str], classes: list[str]) -> dict:
    per = {}
    f1s = []
    for c in classes:
        tp = sum(1 for t, p in zip(y_true, y_pred, strict=True) if t == c and p == c)
        fp = sum(1 for t, p in zip(y_true, y_pred, strict=True) if t != c and p == c)
        fn = sum(1 for t, p in zip(y_true, y_pred, strict=True) if t == c and p != c)
        prec = tp / (tp + fp) if tp + fp else 0.0
        rec = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
        per[c] = {"precision": prec, "recall": rec, "f1": f1, "support": tp + fn}
        f1s.append(f1)
    return {"macro_f1": float(np.mean(f1s)), "per_class": per}


def main() -> int:
    rows, audio, text, slugs = embed_all()
    label_ids = slugs  # label id == slug in this offline harness
    cats = [r["category"] for r in rows]
    folds = [r["fold"] for r in rows]
    cos_all = audio @ text.T  # (N, L) base cosines
    classes = sorted(ESC_TO_SLUG)
    params = FusionParams()
    results: dict[int, dict] = {}
    unknown_stats: dict[int, dict] = {}
    lat = []
    gate_rows: list[tuple[bool, float, float, float]] = []
    for n in NS:
        y_true_all, y_pred_all, top3_hits, rank_true = [], [], [], []
        unk_scores: list[tuple[float, bool]] = []
        novel_flags: dict[str, list[int]] = defaultdict(list)
        for test_fold in sorted(set(folds)):
            test_idx = [i for i, f in enumerate(folds) if f == test_fold]
            train_idx = [i for i, f in enumerate(folds) if f != test_fold]
            for seed in SEEDS if n > 0 else [0]:
                rng = np.random.default_rng(seed)
                ex_idx: list[int] = []
                for c in classes:
                    if c == UNKNOWN_CLASS:
                        continue  # never taught: measures unknown handling
                    pool = [i for i in train_idx if cats[i] == c]
                    ex_idx += list(rng.choice(pool, size=min(n, len(pool)), replace=False)) if n else []
                index = MemoryIndex(
                    vecs=audio[ex_idx] if ex_idx else np.zeros((0, audio.shape[1]), np.float32),
                    label_ids=[ESC_TO_SLUG[cats[i]] for i in ex_idx],
                    recording_ids=[rows[i]["filename"] for i in ex_idx],
                    exemplar_ids=[str(i) for i in ex_idx],
                    weights=np.ones(len(ex_idx), np.float32),
                )
                for i in test_idx:
                    t0 = time.perf_counter()
                    res = fuse(audio[i], label_ids, cos_all[i], index, params)
                    lat.append(time.perf_counter() - t0)
                    truth = ESC_TO_SLUG[cats[i]]
                    ranked = [c.label_id for c in res.candidates]
                    y_true_all.append(truth)
                    y_pred_all.append(ranked[0])
                    top3_hits.append(truth in ranked[:3])
                    rank_true.append(ranked.index(truth) + 1)
                    is_unknown = cats[i] == UNKNOWN_CLASS
                    nearest = res.novelty["nearest_exemplar_similarity"]
                    unk_scores.append((-1.0 if nearest is None else float(nearest), is_unknown))
                    novel_flags["unknown" if is_unknown else "known"].append(int(res.novelty["novel"]))
                    if n == 5:
                        gate_rows.append((is_unknown, -1.0 if nearest is None else float(nearest),
                                          float(res.novelty["fused_margin"]), float(res.novelty["base_entropy_normalised"])))
        slug_classes = [ESC_TO_SLUG[c] for c in classes]
        m = metrics(y_true_all, y_pred_all, slug_classes)
        m["top1"] = float(np.mean([t == p for t, p in zip(y_true_all, y_pred_all, strict=True)]))
        m["top3"] = float(np.mean(top3_hits))
        m["mean_rank_of_truth"] = float(np.mean(rank_true))
        m["n_eval"] = len(y_true_all)
        results[n] = m
        # unknown detection: AUROC of "unknown" vs known using −nearest-exemplar-cosine (n>0 only)
        if n > 0:
            sc = np.array([s for s, _ in unk_scores])
            lab = np.array([u for _, u in unk_scores])
            pos, neg = -sc[lab], -sc[~lab]
            auroc = float(np.mean([(p > q) + 0.5 * (p == q) for p in pos for q in neg[:: max(1, len(neg) // 400)]]))
            unknown_stats[n] = {"auroc_nearest_cosine": auroc,
                                "novel_flag_rate_unknown": float(np.mean(novel_flags["unknown"])),
                                "novel_flag_rate_known": float(np.mean(novel_flags["known"]))}
        else:
            unknown_stats[n] = {"novel_flag_rate_unknown": float(np.mean(novel_flags["unknown"])),
                                "novel_flag_rate_known": float(np.mean(novel_flags["known"]))}
    # novelty gate analysis at n=5: how the three conditions separate known vs unknown clips
    g = np.array([(u, c, m, e) for u, c, m, e in gate_rows], dtype=float)
    unk, kn = g[g[:, 0] == 1], g[g[:, 0] == 0]
    gate = {"n_known": int(len(kn)), "n_unknown": int(len(unk)),
            "nearest_cos_p50_known": float(np.median(kn[:, 1])), "nearest_cos_p50_unknown": float(np.median(unk[:, 1])),
            "margin_p50_known": float(np.median(kn[:, 2])), "margin_p50_unknown": float(np.median(unk[:, 2])),
            "entropy_p50_known": float(np.median(kn[:, 3])), "entropy_p50_unknown": float(np.median(unk[:, 3])),
            "settings": {}}
    for tau_n, tau_m, tau_e in [(0.55, 0.60, 0.25), (0.55, 0.50, 0.30), (0.60, 0.60, 0.25), (0.50, 0.60, 0.25), (0.55, 1.0, 0.0), (0.55, 0.0, 1.0)]:
        f_k = float(np.mean((kn[:, 1] < tau_n) & ((kn[:, 2] < tau_m) | (kn[:, 3] > tau_e))))
        f_u = float(np.mean((unk[:, 1] < tau_n) & ((unk[:, 2] < tau_m) | (unk[:, 3] > tau_e))))
        gate["settings"][f"tau_n={tau_n},tau_m={tau_m},tau_e={tau_e}"] = {"flag_rate_known": f_k, "flag_rate_unknown": f_u}
    report = {
        "novelty_gate_analysis_n5": gate,
        "dataset": "ESC-50 subset (6 classes, 5 folds), label space = project vocabulary (39 labels)",
        "unknown_class_held_out_of_memory": UNKNOWN_CLASS, "params": params.__dict__, "seeds": SEEDS,
        "fusion_latency_ms_p50": float(np.median(lat) * 1000), "results": results, "unknown": unknown_stats,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    json.dump(report, open(OUT / "esc50_personalization.json", "w"), indent=2)
    lines = ["| exemplars/class | top-1 | top-3 | macro-F1 (6 cls) | mean rank of truth | novel-flag known / unknown |", "|---|---|---|---|---|---|"]
    for n in NS:
        r, u = results[n], unknown_stats[n]
        lines.append(f"| {n} | {r['top1']:.3f} | {r['top3']:.3f} | {r['macro_f1']:.3f} | {r['mean_rank_of_truth']:.2f} | {u['novel_flag_rate_known']:.2f} / {u['novel_flag_rate_unknown']:.2f} |")
    lines.append("")
    lines.append("Per-class recall (n=0 → n=5): " + ", ".join(
        f"{c}: {results[0]['per_class'][ESC_TO_SLUG[c]]['recall']:.2f}→{results[5]['per_class'][ESC_TO_SLUG[c]]['recall']:.2f}" for c in classes))
    if 5 in unknown_stats and "auroc_nearest_cosine" in unknown_stats[5]:
        lines.append(f"\nUnknown-class (wind, never taught) vs known: AUROC of nearest-exemplar cosine = {unknown_stats[5]['auroc_nearest_cosine']:.3f} (n=5)")
    lines.append("\nNovelty gate at n=5, novel = nearest<tau_n AND (margin<tau_m OR entropy>tau_e) — flag rate on known / unknown clips:")
    for k, v in gate["settings"].items():
        lines.append(f"- {k}: {v['flag_rate_known']:.2f} / {v['flag_rate_unknown']:.2f}")
    lines.append(f"- medians known vs unknown: nearest cos {gate['nearest_cos_p50_known']:.2f} vs {gate['nearest_cos_p50_unknown']:.2f}, "
                 f"fused margin {gate['margin_p50_known']:.2f} vs {gate['margin_p50_unknown']:.2f}, base entropy {gate['entropy_p50_known']:.2f} vs {gate['entropy_p50_unknown']:.2f}")
    md = "\n".join(lines)
    (OUT / "esc50_personalization.md").write_text(md + "\n")
    print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
