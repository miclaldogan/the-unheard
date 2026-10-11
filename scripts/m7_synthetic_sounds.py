# ruff: noqa: E501
"""M7: deterministic synthetic field recordings, authored here and free to publish.

    python scripts/m7_synthetic_sounds.py generate          # write WAVs + manifest to server/data/m7_synthetic/
    python scripts/m7_synthetic_sounds.py verify            # decode each file through the real ingest validator
    python scripts/m7_synthetic_sounds.py describe          # print the set and what each file is for

Why this exists: the only audio the project had was ESC-50, which is CC BY-NC and must never appear in a public
demo or in Git (FINAL-PUBLICATION-CHECKLIST.md section B). These signals are synthesised from scratch by this
script, so they carry the repository's own licence and can be shown publicly. They are *not* field recordings and
nothing here may be presented as one; every upload is stamped ``synthetic: true`` by ``m7_upload.py``.

The set mirrors the structure ``m55_real_journey.py`` depends on, which is not arbitrary:

* group ``gutter`` - three different takes of rain in a metal gutter. Two are taught the name "Roof gutter" and the
  third is held out, which is what proves personalised retrieval memory: the name is absent from the held-out
  clip's top ranks before teaching and present after, with ``n_exemplars == 2``.
* group ``bells`` - three different takes of a tolling bell. All three are taught, giving the Composed renderer the
  three taught sources it needs.

Synthesis is modal/stochastic rather than sample-based: the gutter is shaped broadband noise plus Poisson droplet
impulses ringing a short metal resonance; the bell is a struck inharmonic partial series with per-partial decay and
slight detuning, placed in a synthetic room. Every variant is seeded, so the same commit always produces the same
bytes.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf
from numpy.typing import NDArray
from scipy.signal import butter, lfilter, sosfilt

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(os.environ.get("UNHEARD_SET_DIR", str(ROOT / "server" / "data" / "m7_synthetic")))

SR = 48_000  # the backend's canonical rate; generating here avoids a resample on ingest
DURATION_S = 10.0  # inside the 3-30 s ingest window with margin at both ends
TARGET_PEAK = 0.89  # below clipping_peak 0.99, so no clipping flag
TARGET_RMS_DBFS = -22.0  # well above the -60 rejection and the -40 "quiet" flag


# ---------------------------------------------------------------------------- helpers


def _rng(seed: int) -> np.random.Generator:
    return np.random.default_rng(seed)


def _bandpass(x: NDArray[np.float64], lo: float, hi: float, order: int = 4) -> NDArray[np.float64]:
    nyq = SR / 2.0
    sos = butter(order, [max(lo, 1.0) / nyq, min(hi, nyq - 1.0) / nyq], btype="band", output="sos")
    return np.asarray(sosfilt(sos, x), dtype=np.float64)


def _lowpass(x: NDArray[np.float64], cut: float, order: int = 4) -> NDArray[np.float64]:
    sos = butter(order, min(cut, SR / 2.0 - 1.0) / (SR / 2.0), btype="low", output="sos")
    return np.asarray(sosfilt(sos, x), dtype=np.float64)


def _pink(n: int, rng: np.random.Generator) -> NDArray[np.float64]:
    """Approximate 1/f noise with a one-pole cascade; rain and wind are not white."""
    white = rng.standard_normal(n)
    b = [0.049922035, -0.095993537, 0.050612699, -0.004408786]
    a = [1.0, -2.494956002, 2.017265875, -0.522189400]
    return np.asarray(lfilter(b, a, white), dtype=np.float64)


def _room(x: NDArray[np.float64], seconds: float, mix: float, seed: int) -> NDArray[np.float64]:
    """Convolve with an exponentially decaying noise burst: a cheap, deterministic room."""
    rng = _rng(seed)
    n = int(seconds * SR)
    ir = rng.standard_normal(n) * np.exp(-np.arange(n) / (0.28 * n))
    ir = _lowpass(ir, 6500.0)
    ir /= np.max(np.abs(ir)) + 1e-12
    wet = np.convolve(x, ir, mode="full")[: x.size]
    wet /= np.max(np.abs(wet)) + 1e-12
    return (1.0 - mix) * x + mix * wet * np.max(np.abs(x))


def _normalise(x: NDArray[np.float64]) -> NDArray[np.float64]:
    """Remove DC, hit the RMS target, then cap the peak. Keeps every quality flag clear."""
    x = x - float(np.mean(x))
    rms = float(np.sqrt(np.mean(x * x)))
    if rms > 1e-9:
        x = x * (10.0 ** (TARGET_RMS_DBFS / 20.0) / rms)
    peak = float(np.max(np.abs(x)))
    if peak > TARGET_PEAK:
        x = x * (TARGET_PEAK / peak)
    return x


def _fade(x: NDArray[np.float64], seconds: float = 0.12) -> NDArray[np.float64]:
    k = int(seconds * SR)
    env = np.ones(x.size)
    env[:k] = np.linspace(0.0, 1.0, k)
    env[-k:] = np.linspace(1.0, 0.0, k)
    return x * env


# ---------------------------------------------------------------------------- gutter


def rain_gutter(
    seed: int,
    droplets_per_s: float,
    wind: float,
    gust_hz: float,
    resonance_hz: float,
) -> NDArray[np.float64]:
    """Rain falling into a metal gutter: shaped hiss, gusts, and resonant droplet impacts."""
    rng = _rng(seed)
    n = int(DURATION_S * SR)
    t = np.arange(n) / SR

    hiss = _bandpass(_pink(n, rng), 600.0, 11_000.0) * 0.55
    gusts = 1.0 + 0.35 * np.sin(2 * np.pi * gust_hz * t + rng.uniform(0, 2 * np.pi))
    hiss *= gusts

    low = _lowpass(_pink(n, rng), 320.0) * wind

    # Poisson droplet onsets, each ringing the gutter's metal resonance briefly. Density matters:
    # sparse pitched rings read to CLAP as wind chimes, dense ones as rain (see docs/M7-SYNTHETIC-AUDIO.md).
    drops = np.zeros(n)
    count = int(droplets_per_s * DURATION_S)
    onsets = rng.integers(0, n, size=count)
    for i in onsets:
        decay_s = float(rng.uniform(0.018, 0.055))
        length = int(decay_s * SR)
        if i + length >= n:
            continue
        freq = float(resonance_hz * rng.uniform(0.72, 1.45))
        local = np.arange(length) / SR
        ring = np.sin(2 * np.pi * freq * local) * np.exp(-local / (decay_s / 3.0))
        drops[i : i + length] += ring * float(rng.uniform(0.25, 1.0))

    mixed = hiss + low + drops * 0.5
    return _fade(_normalise(_room(mixed, 0.22, 0.18, seed + 101)))


# ---------------------------------------------------------------------------- bells

# Ratios of a real tuned bell: hum, prime, tierce (minor third), quint, nominal, and two upper partials.
BELL_RATIOS = [0.5, 1.0, 1.1892, 1.5, 2.0, 2.5, 3.0]
BELL_DECAYS = [7.5, 5.5, 3.6, 2.4, 1.6, 0.9, 0.6]  # seconds; high partials die first
BELL_GAINS = [0.55, 1.0, 0.72, 0.40, 0.46, 0.22, 0.14]


def bell_toll(
    seed: int,
    f0: float,
    strikes: list[float],
    brightness: float,
    room_s: float,
    room_mix: float,
) -> NDArray[np.float64]:
    """A tolling bell: struck inharmonic partials, detuned slightly so the tail beats."""
    rng = _rng(seed)
    n = int(DURATION_S * SR)
    out = np.zeros(n)

    for strike_at in strikes:
        start = int(strike_at * SR)
        if start >= n:
            continue
        length = n - start
        local = np.arange(length) / SR
        voice = np.zeros(length)

        for ratio, decay, gain in zip(BELL_RATIOS, BELL_DECAYS, BELL_GAINS, strict=True):
            detune = float(rng.uniform(-0.0035, 0.0035))
            freq = f0 * ratio * (1.0 + detune)
            if freq >= SR / 2.0:
                continue
            partial = np.sin(2 * np.pi * freq * local + rng.uniform(0, 2 * np.pi))
            # a second, slightly detuned copy makes the long tail shimmer the way a real bell does
            partial += 0.6 * np.sin(2 * np.pi * freq * (1.0 + 0.0012) * local)
            voice += gain * partial * np.exp(-local / decay)

        # the strike itself: a short filtered burst, brighter when the bell is close
        attack_n = int(0.03 * SR)
        burst = rng.standard_normal(min(attack_n, length))
        burst = _bandpass(burst, 1800.0, 9000.0 * brightness)
        burst *= np.exp(-np.arange(burst.size) / (attack_n / 3.0))
        voice[: burst.size] += burst * 0.5 * brightness

        out[start:] += voice * float(rng.uniform(0.9, 1.0))

    out = _lowpass(out, 3000.0 + 7000.0 * brightness)
    return _fade(_normalise(_room(out, room_s, room_mix, seed + 211)))


# ---------------------------------------------------------------------------- the set


@dataclass(frozen=True)
class Specimen:
    group: str
    name: str
    teach_as: str | None  # the label to teach, or None when the clip is held out
    role: str
    description: str
    params: dict[str, Any] = field(default_factory=dict)

    @property
    def filename(self) -> str:
        return f"{self.name}.wav"


SPECIMENS: list[Specimen] = [
    Specimen(
        "gutter",
        "gutter-light",
        "Roof gutter",
        "taught exemplar 1",
        "Thin rain, sparse droplets, almost no wind.",
        {
            "seed": 7001,
            "droplets_per_s": 150.0,
            "wind": 0.10,
            "gust_hz": 0.17,
            "resonance_hz": 1850.0,
        },
    ),
    Specimen(
        "gutter",
        "gutter-steady",
        "Roof gutter",
        "taught exemplar 2",
        "Steadier rain, denser impacts, a little low wind underneath.",
        {
            "seed": 7002,
            "droplets_per_s": 380.0,
            "wind": 0.22,
            "gust_hz": 0.11,
            "resonance_hz": 1620.0,
        },
    ),
    Specimen(
        "gutter",
        "gutter-windy",
        None,
        "HELD OUT - the memory proof",
        "Gusty rain in the same gutter. Never taught; its prediction is the evidence that memory works.",
        {
            "seed": 7003,
            "droplets_per_s": 300.0,
            "wind": 0.42,
            "gust_hz": 0.23,
            "resonance_hz": 1980.0,
        },
    ),
    Specimen(
        "bells",
        "bells-distant",
        "Bells",
        "taught + composition source 1",
        "A bell heard from far off: dark, reverberant, two slow strikes.",
        {
            "seed": 8001,
            "f0": 232.0,
            "strikes": [0.6, 5.1],
            "brightness": 0.45,
            "room_s": 1.6,
            "room_mix": 0.45,
        },
    ),
    Specimen(
        "bells",
        "bells-near",
        "Bells",
        "taught + composition source 2",
        "The same bell up close: bright strike transient, three tolls.",
        {
            "seed": 8002,
            "f0": 288.0,
            "strikes": [0.4, 3.6, 6.9],
            "brightness": 1.0,
            "room_s": 0.8,
            "room_mix": 0.22,
        },
    ),
    Specimen(
        "bells",
        "bells-resonant",
        "Bells",
        "taught + composition source 3",
        "A larger bell in a stone space: low hum, long beating tail.",
        {
            "seed": 8003,
            "f0": 174.0,
            "strikes": [0.5, 4.8],
            "brightness": 0.65,
            "room_s": 2.4,
            "room_mix": 0.55,
        },
    ),
]


def render(spec: Specimen) -> NDArray[np.float64]:
    if spec.group == "gutter":
        return rain_gutter(**spec.params)
    if spec.group == "bells":
        return bell_toll(**spec.params)
    raise ValueError(f"unknown group {spec.group!r}")


def measure(x: NDArray[np.float64]) -> dict[str, float]:
    peak = float(np.max(np.abs(x)))
    rms = float(np.sqrt(np.mean(x * x)))
    return {
        "duration_s": round(x.size / SR, 3),
        "peak": round(peak, 4),
        "peak_dbfs": round(20.0 * float(np.log10(max(peak, 1e-12))), 2),
        "rms_dbfs": round(20.0 * float(np.log10(max(rms, 1e-12))), 2),
        "dc_offset": round(float(np.mean(x)), 6),
    }


def cmd_generate() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    entries = []
    for spec in SPECIMENS:
        x = render(spec)
        path = OUT / spec.filename
        sf.write(path, x, SR, format="WAV", subtype="PCM_16")
        m = measure(x)
        entries.append(
            {
                "file": spec.filename,
                "group": spec.group,
                "teach_as": spec.teach_as,
                "role": spec.role,
                "description": spec.description,
                "params": spec.params,
                "measured": m,
                "bytes": path.stat().st_size,
            }
        )
        held = "" if spec.teach_as else "   <- held out"
        print(
            f"{spec.filename:22s} {m['duration_s']:5.2f}s  "
            f"rms {m['rms_dbfs']:6.2f} dBFS  peak {m['peak']:.3f}{held}"
        )

    manifest = {
        "generator": "scripts/m7_synthetic_sounds.py",
        "provenance": "synthesised from scratch by this script; NOT a field recording",
        "licence": "same as this repository (MIT); safe to publish",
        "sample_rate": SR,
        "duration_s": DURATION_S,
        "deterministic": "seeded; the same commit produces identical bytes",
        "specimens": entries,
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"\n{len(entries)} files + manifest.json -> {OUT}")
    return 0


def cmd_verify() -> int:
    """Run each file through the backend's own decoder and validator. No server, no model."""
    sys.path.insert(0, str(ROOT / "server"))
    from unheard.config import get_settings  # noqa: PLC0415
    from unheard.ingest.decode import Decoder  # noqa: PLC0415
    from unheard.ingest.sniff import sniff_container  # noqa: PLC0415
    from unheard.ingest.validate import Limits, validate_decoded  # noqa: PLC0415

    s = get_settings()
    decoder = Decoder()
    if not decoder.ffmpeg_available():
        print("ffmpeg/ffprobe not on PATH; the backend would fall back to its own reader")
    limits = Limits(
        min_duration_s=s.min_duration_s,
        max_duration_s=s.max_duration_s,
        min_source_sample_rate=s.min_source_sample_rate,
        max_source_sample_rate=s.max_source_sample_rate,
        silence_dbfs=s.silence_dbfs,
        clipping_peak=s.clipping_peak,
        clipping_flag_ratio=s.clipping_flag_ratio,
    )
    failures = 0
    for spec in SPECIMENS:
        path = OUT / spec.filename
        if not path.exists():
            print(f"{spec.filename:22s} MISSING - run `generate` first")
            failures += 1
            continue
        try:
            data = path.read_bytes()
            sniff = sniff_container(data[:64])
            if sniff is None:
                raise RuntimeError("container not recognised from its own bytes")
            decoded = decoder.decode(data, sniff.container, s.canonical_sample_rate)
            _, quality = validate_decoded(
                decoded.samples,
                s.canonical_sample_rate,
                decoded.source.sample_rate,
                decoded.source.channels,
                limits,
            )
        except Exception as e:  # noqa: BLE001 - we want the reason printed, not a traceback
            print(f"{spec.filename:22s} REJECTED  {type(e).__name__}: {e}")
            failures += 1
            continue
        flags = ", ".join(quality["flags"]) or "none"
        print(
            f"{spec.filename:22s} accepted  rms {quality['rms_dbfs']:6.2f} dBFS  "
            f"peak {quality['peak']:.3f}  flags: {flags}"
        )
    print("\nall accepted, no quality flags" if not failures else f"\n{failures} problem(s)")
    return 1 if failures else 0


def cmd_describe() -> int:
    print(__doc__)
    for group in ("gutter", "bells"):
        print(f"\n{group}")
        for spec in (s for s in SPECIMENS if s.group == group):
            teach = spec.teach_as or "(not taught)"
            print(f"  {spec.filename:22s} teach as {teach:14s} {spec.role}")
            print(f"  {'':22s} {spec.description}")
    return 0


PROBE_PROMPTS = [
    "rain",
    "rain falling on a roof",
    "water dripping in a metal gutter",
    "wind",
    "church bells ringing",
    "a large bell tolling",
    "a gong",
    "a metal chime",
    "a piano",
    "birds singing",
    "traffic on a busy street",
    "human speech",
    "silence",
]


def cmd_probe() -> int:
    """Embed the set with real CLAP and report zero-shot labels and group separation.

    Needs the cached weights and the ml extra:
        HF_HUB_OFFLINE=1 uv run --extra ml python ../scripts/m7_synthetic_sounds.py probe
    """
    import itertools  # noqa: PLC0415

    sys.path.insert(0, str(ROOT / "server"))
    from unheard.models.clap import ClapAudioModel  # noqa: PLC0415
    from unheard.models.contracts import AudioInferenceInput  # noqa: PLC0415

    model = ClapAudioModel(device="cpu", allow_download=False, threads=2)
    model.load()
    print(f"loaded {model.name} dim={model.embedding_dim} in {model.load_seconds:.1f}s\n")
    model.set_label_space(list(zip(PROBE_PROMPTS, model.embed_text(PROBE_PROMPTS), strict=True)))

    vecs: dict[str, NDArray[np.float32]] = {}
    labels: dict[str, list[tuple[str, float]]] = {}
    for spec in SPECIMENS:
        x, sr = sf.read(OUT / spec.filename, dtype="float64", always_2d=False)
        res = model.infer(
            AudioInferenceInput(
                recording_id=spec.filename,
                samples=np.asarray(x),
                sample_rate=int(sr),
                duration_s=x.size / sr,
            )
        )
        if res.status != "ok":
            print(f"{spec.filename}: inference failed: {res.error}")
            return 1
        vecs[spec.filename] = res.embedding.vector
        labels[spec.filename] = [(p.label, p.score) for p in res.predictions[:4]]
        print(f"{spec.filename:22s} [{spec.group}]")
        for name, score in labels[spec.filename]:
            print(f"    {score:+.4f}  {name}")
        print()

    intra: list[float] = []
    inter: list[float] = []
    pairs = []
    by_file = {s.filename: s for s in SPECIMENS}
    for a, b in itertools.combinations([s.filename for s in SPECIMENS], 2):
        sim = float(np.dot(vecs[a], vecs[b]))
        same = by_file[a].group == by_file[b].group
        (intra if same else inter).append(sim)
        pairs.append({"a": a, "b": b, "same_group": same, "cosine": round(sim, 4)})

    sep = float(np.mean(intra) - np.mean(inter))
    print(
        f"intra-group mean {np.mean(intra):+.4f} (n={len(intra)})   "
        f"inter-group mean {np.mean(inter):+.4f} (n={len(inter)})   separation {sep:+.4f}"
    )

    held = next(s for s in SPECIMENS if s.teach_as is None)
    taught = [s for s in SPECIMENS if s.group == held.group and s.teach_as]
    print(f"\nheld out: {held.filename}")
    for s in taught:
        print(
            f"  cos to taught {s.filename:22s} {float(np.dot(vecs[held.filename], vecs[s.filename])):+.4f}"
        )
    other = max(
        (s for s in SPECIMENS if s.group != held.group),
        key=lambda s: float(np.dot(vecs[held.filename], vecs[s.filename])),
    )
    print(
        f"  cos to nearest other-group {other.filename:12s} {float(np.dot(vecs[held.filename], vecs[other.filename])):+.4f}"
    )

    report = {
        "model": model.name,
        "embedding_dim": model.embedding_dim,
        "prompts": PROBE_PROMPTS,
        "zero_shot_top4": {
            k: [{"label": n, "score": round(v, 4)} for n, v in t] for k, t in labels.items()
        },
        "pairs": pairs,
        "intra_group_mean": round(float(np.mean(intra)), 4),
        "inter_group_mean": round(float(np.mean(inter)), 4),
        "separation": round(sep, 4),
        "caveat": (
            "Variants within a group share one synthesis algorithm and differ only by parameters, so they are more "
            "self-similar than genuinely different field recordings of the same source. The retrieval result this set "
            "produces is therefore an easier case than the ESC-50 measurement (held-out similarity 0.837261)."
        ),
    }
    (OUT / "clap-probe.json").write_text(json.dumps(report, indent=2) + "\n")
    print(f"\nwrote {OUT / 'clap-probe.json'}")
    return 0


COMMANDS = {
    "generate": cmd_generate,
    "verify": cmd_verify,
    "describe": cmd_describe,
    "probe": cmd_probe,
}


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in COMMANDS:
        print(f"usage: {Path(sys.argv[0]).name} {{{'|'.join(COMMANDS)}}}")
        return 2
    return COMMANDS[sys.argv[1]]()


if __name__ == "__main__":
    raise SystemExit(main())
