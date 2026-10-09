# ruff: noqa: E501
"""Objective diagnostics of the M4 demo compositions (reads ``server/data/m4_demo``).

Not a substitute for listening: these are proxies for the defects a listener would notice.

    cd server && uv run python ../scripts/m4_diagnose.py [--dir data/m4_demo] [--json out.json]

Per composition:
* loudness   — BS.1770-style LUFS, sample peak, 4x-oversampled peak, clipped-sample ratio, crest factor
* wash       — "stationary share": fraction of master energy that a per-bin temporal median predicts
               (steady background). High = broadband wash, low = events stand out.
* masking    — mean pairwise overlap of the stems' band-energy distributions while both sound
               (1 = identical spectra, 0 = disjoint) and how much quieter the weakest layer is
* repetition — adjacent-bar similarity of the log-mel profile and the longest run of near-identical bars
* harshness  — share of energy above 6 kHz and 3–8 kHz level relative to 250 Hz–1 kHz in transient frames
* development — per section: RMS, spectral centroid, number of sounding layers, event rate
"""

from __future__ import annotations

import argparse
import json
from itertools import combinations
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy import ndimage, signal

from unheard.music.render import loudness_lufs

ROOT = Path(__file__).resolve().parents[1]
BANDS = [(20, 250), (250, 1000), (1000, 4000), (4000, 8000), (8000, 20000)]
NPERSEG, HOP = 2048, 512


def _spec(x: np.ndarray, sr: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    f, t, s = signal.stft(x, sr, nperseg=NPERSEG, noverlap=NPERSEG - HOP)
    return f, t, np.abs(s) ** 2


def _band_energy(p: np.ndarray, f: np.ndarray) -> np.ndarray:
    return np.stack([p[(f >= lo) & (f < hi)].sum(0) for lo, hi in BANDS])


def ev_all(plan: dict, tid: str) -> list:  # type: ignore[type-arg]
    return [e for e in plan["events"] if e["track"] == tid and e["kind"] == "slice"]


def diagnose(name: str, d: Path) -> dict:  # type: ignore[type-arg]
    master, sr = sf.read(d / f"{name}_master.wav", dtype="float64")
    plan = json.loads((d / f"{name}_plan.json").read_text())
    mono = master.mean(1)
    f, t, p = _spec(mono, sr)
    total = p.sum()

    over = signal.resample_poly(master, 4, 1, axis=0)
    out: dict = {  # type: ignore[type-arg]
        "name": name,
        "duration_s": round(len(master) / sr, 2),
        "lufs": round(loudness_lufs(master), 1),
        "sample_peak_dbfs": round(20 * np.log10(np.max(np.abs(master))), 2),
        "oversampled_peak_dbfs": round(20 * np.log10(np.max(np.abs(over))), 2),
        "clipped_ratio": float(np.mean(np.abs(master) >= 0.999)),
        "crest_db": round(20 * np.log10(np.max(np.abs(master)) / np.sqrt(np.mean(master**2))), 1),
    }

    # wash: how much of the energy is explained by the steady (temporal-median) background
    bg = ndimage.median_filter(p, size=(1, int(2.0 * sr / HOP) | 1), mode="nearest")
    out["stationary_share"] = round(float(np.sum(np.minimum(p, bg)) / total), 3)
    secs = plan["sections"]
    out["stationary_share_by_section"] = {}
    for s in secs:
        m = (t >= s["start_s"]) & (t < s["end_s"])
        out["stationary_share_by_section"][s["name"]] = round(
            float(np.sum(np.minimum(p[:, m], bg[:, m])) / max(p[:, m].sum(), 1e-12)), 3
        )

    # stems: masking, contribution, activity
    stems = {}
    for tr in plan["tracks"]:
        x, _ = sf.read(d / f"{name}_{tr['id']}.wav", dtype="float64")
        stems[tr["id"]] = x.mean(1)
    eb = {k: _band_energy(_spec(v, sr)[2], f) for k, v in stems.items()}
    frames = min(e.shape[1] for e in eb.values())
    act = {k: eb[k][:, :frames].sum(0) for k in eb}
    floor = {k: np.percentile(act[k], 5) * 4 + 1e-14 for k in act}
    live = {k: act[k] > np.maximum(floor[k], 1e-9 * np.max(act[k])) for k in act}
    overlaps = []
    for a, b in combinations(stems, 2):
        both = live[a] & live[b]
        if both.sum() < 20:
            continue
        pa, pb = eb[a][:, :frames][:, both].sum(1), eb[b][:, :frames][:, both].sum(1)
        pa, pb = pa / pa.sum(), pb / pb.sum()
        overlaps.append((a, b, float(np.minimum(pa, pb).sum())))
    out["masking_overlap_mean"] = (
        round(float(np.mean([o[2] for o in overlaps])), 3) if overlaps else None
    )
    out["masking_worst_pair"] = (
        max(overlaps, key=lambda o: o[2])[:2] + (round(max(o[2] for o in overlaps), 3),)
        if overlaps
        else None
    )  # type: ignore[assignment]
    rms = {k: float(np.sqrt(np.mean(v**2))) for k, v in stems.items()}
    out["stem_rms_dbfs"] = {k: round(20 * np.log10(max(v, 1e-9)), 1) for k, v in rms.items()}
    out["weakest_layer_below_loudest_db"] = round(
        20 * np.log10(max(rms.values()) / max(min(rms.values()), 1e-9)), 1
    )
    out["layer_active_ratio"] = {k: round(float(live[k].mean()), 2) for k in live}

    # event clarity: own-layer energy vs all other layers inside each hit/note window (dB)
    clarity: dict = {}  # type: ignore[type-arg]
    for tr in plan["tracks"]:
        if tr["role"] not in ("percussion", "tonal_motif", "accent", "rhythmic_texture"):
            continue
        vals = []
        for e in ev_all(plan, tr["id"]):
            a0, a1 = int(e["t"] * sr), int((e["t"] + min(e["dur"], 0.4)) * sr)
            own = float(np.sum(stems[tr["id"]][a0:a1] ** 2)) + 1e-12
            oth = (
                sum(float(np.sum(v[a0:a1] ** 2)) for k, v in stems.items() if k != tr["id"]) + 1e-12
            )
            vals.append(10 * np.log10(own / oth))
        if vals:
            clarity[tr["id"]] = {
                "role": tr["role"],
                "median_db": round(float(np.median(vals)), 1),
                "p10_db": round(float(np.percentile(vals, 10)), 1),
            }
    out["event_clarity"] = clarity

    # repetition: adjacent-bar similarity of the mean log-mel profile
    bar = plan["bar_s"]
    n_bars = int(plan["duration_s"] / bar)
    prof = []
    for i in range(n_bars):
        m = (t >= i * bar) & (t < (i + 1) * bar)
        v = np.log10(_band_energy(p[:, m], f).sum(1) + 1e-12)
        prof.append(v - v.mean())
    prof_a = np.array(prof)
    sims = [
        float(
            np.dot(prof_a[i], prof_a[i + 1])
            / (np.linalg.norm(prof_a[i]) * np.linalg.norm(prof_a[i + 1]) + 1e-12)
        )
        for i in range(len(prof_a) - 1)
    ]
    # hit-timing repetition: onset-envelope pattern correlation between adjacent bars
    env = np.sqrt(p.sum(0))
    pat = []
    for i in range(n_bars):
        m = (t >= i * bar) & (t < (i + 1) * bar)
        e = env[m]
        pat.append(
            np.interp(np.linspace(0, len(e) - 1, 32), np.arange(len(e)), e)
            if len(e) > 1
            else np.zeros(32)
        )
    pat_a = np.array(pat)
    psim = [
        float(np.corrcoef(pat_a[i], pat_a[i + 1])[0, 1])
        if pat_a[i].std() > 0 and pat_a[i + 1].std() > 0
        else 1.0
        for i in range(len(pat_a) - 1)
    ]
    run = best = 0
    for v in psim:
        run = run + 1 if v > 0.98 else 0
        best = max(best, run)
    out["bar_profile_similarity_mean"] = round(float(np.mean(sims)), 3)
    out["bar_hit_pattern_similarity_mean"] = round(float(np.mean(psim)), 3)
    out["longest_run_of_identical_bars"] = best + 1 if best else 0

    # harshness
    hf = _band_energy(p, f)
    out["energy_above_6k_share"] = round(float(p[f >= 6000].sum() / total), 4)
    loud = env > np.percentile(env, 90)
    mid = hf[1][loud].sum() + 1e-12
    out["transient_3to8k_vs_250to1k_db"] = round(
        float(10 * np.log10(p[(f >= 3000) & (f < 8000)][:, loud].sum() / mid)), 1
    )

    # development
    ev = plan["events"]
    dev = []
    for s in secs:
        m = (t >= s["start_s"]) & (t < s["end_s"])
        cen = float((f[:, None] * p[:, m]).sum() / max(p[:, m].sum(), 1e-12))
        tr_active = {e["track"] for e in ev if s["start_s"] <= e["t"] < s["end_s"]}
        n_hits = sum(1 for e in ev if e["kind"] == "slice" and s["start_s"] <= e["t"] < s["end_s"])
        seg = master[int(s["start_s"] * sr) : int(s["end_s"] * sr)]
        dev.append(
            {
                "section": s["name"],
                "rms_dbfs": round(float(20 * np.log10(max(np.sqrt(np.mean(seg**2)), 1e-9))), 1),
                "centroid_hz": round(cen),
                "layers": len(tr_active),
                "slice_events_per_s": round(n_hits / max(s["end_s"] - s["start_s"], 1e-6), 2),
            }
        )
    out["development"] = dev
    return out


def verdicts(r: dict) -> list[str]:  # type: ignore[type-arg]
    v = []
    if r["stationary_share"] > 0.7:
        v.append(f"WASH: {r['stationary_share']:.0%} of the energy is steady background")
    if r["masking_overlap_mean"] and r["masking_overlap_mean"] > 0.75:
        v.append(f"MASKING: layers share {r['masking_overlap_mean']:.0%} of their spectrum")
    if r["weakest_layer_below_loudest_db"] > 14:
        v.append(
            f"BALANCE: weakest layer is {r['weakest_layer_below_loudest_db']} dB below the loudest"
        )
    if r["bar_hit_pattern_similarity_mean"] > 0.9 or r["longest_run_of_identical_bars"] >= 6:
        v.append(
            f"REPETITION: hit patterns repeat (mean {r['bar_hit_pattern_similarity_mean']}, run {r['longest_run_of_identical_bars']})"
        )
    if r["transient_3to8k_vs_250to1k_db"] > 3:
        v.append(
            f"HARSH: 3–8 kHz is {r['transient_3to8k_vs_250to1k_db']} dB above 250 Hz–1 kHz in loud frames"
        )
    if r["clipped_ratio"] > 0 or r["oversampled_peak_dbfs"] > 0.0:
        v.append("CLIP: peaks reach full scale")
    d = r["development"]
    spread = max(x["rms_dbfs"] for x in d) - min(x["rms_dbfs"] for x in d)
    if spread > 15:
        v.append(
            f"DYNAMICS: section loudness spread is {spread:.0f} dB; quiet parts may vanish in a real room"
        )
    low = [k for k, c in r["event_clarity"].items() if c["median_db"] < -3]
    if low:
        v.append(f"CLARITY: hits/notes of {low} sit more than 3 dB below the other layers (median)")
    if not (d[2]["rms_dbfs"] > d[0]["rms_dbfs"] + 6 and d[3]["rms_dbfs"] < d[2]["rms_dbfs"] - 3):
        v.append("DEVELOPMENT: convergence is not clearly louder than the ends")
    return v or ["no defect flagged by these proxies"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=str(ROOT / "server" / "data" / "m4_demo"))
    ap.add_argument("--json", default=None)
    a = ap.parse_args()
    d = Path(a.dir)
    res = {}
    for name in ("A_natural", "B_urban", "C_hybrid"):
        res[name] = diagnose(name, d)
        res[name]["verdicts"] = verdicts(res[name])
        print(json.dumps(res[name], indent=1))
    if a.json:
        Path(a.json).write_text(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
