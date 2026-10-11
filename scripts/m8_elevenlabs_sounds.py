# ruff: noqa: E501
"""M8: the demo sound set generated with the ElevenLabs sound-effects API instead of NumPy.

    ELEVENLABS_API_KEY=... python scripts/m8_elevenlabs_sounds.py generate [--pack] [--only NAME] [--force]
    python scripts/m8_elevenlabs_sounds.py normalise        # re-level existing clips without calling the API
    python scripts/m8_elevenlabs_sounds.py describe

Same six clips, names, groups and teaching labels as ``m7_synthetic_sounds.py`` (so ``m7_synthetic_journey.py`` can
run on them with ``UNHEARD_SET_DIR``), but the audio comes from a text-to-sound model. The key is read from the
environment only and never written anywhere. Output is git-ignored; the prompts and a manifest (prompt, model,
duration, sha256) are written next to the audio so the set is auditable.

These are AI-generated sounds, not field recordings, and must be described that way. Check the ElevenLabs terms for
your plan (attribution and commercial-use rules differ between tiers) before publishing the audio.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parent))
from m7_synthetic_sounds import SPECIMENS  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "server" / "data" / "m8_elevenlabs"
URL = "https://api.elevenlabs.io/v1/sound-generation?output_format=mp3_44100_128"
MODEL = "eleven_text_to_sound_v2"
DURATION_S = 10.0
PROMPT_INFLUENCE = 0.6

PROMPTS: dict[str, str] = {
    "gutter-light": "Light rain dripping into a metal roof gutter, sparse droplets, quiet, close microphone, outdoors, no music",
    "gutter-steady": "Steady rain falling and running through a metal roof gutter, dense drops, calm, field recording, no music",
    "gutter-windy": "Rain in a metal roof gutter with gusts of wind blowing through, outdoors, field recording, no music",
    "bells-distant": "A church bell tolling slowly from far away, two strikes, long reverberant tail, outdoors, no music",
    "bells-near": "A large church bell tolling close by, three bright strikes, ringing decay, no music",
    "bells-resonant": "A very large low bell struck inside a stone church, deep hum and long beating tail, no music",
}


# The demo pack: five families, three different takes each, no human voices. Names follow ``<group>-<take>``.
PACK: list[tuple[str, str, str]] = [
    (
        "wind",
        "wind-leaves",
        "Wind moving through leaves of tall trees in a park, gentle gusts, outdoors, no music",
    ),
    (
        "wind",
        "wind-grass",
        "Steady breeze across an open grass field, low soft whoosh, distant, outdoors, no music",
    ),
    (
        "wind",
        "wind-gusty",
        "Strong gusts of wind rushing past a microphone then dying down, outdoors, no music",
    ),
    (
        "steps",
        "steps-gravel",
        "Slow footsteps walking on a gravel path, crunching stones, outdoors, no talking, no music",
    ),
    (
        "steps",
        "steps-leaves",
        "Footsteps walking through dry autumn leaves, crunchy, steady pace, outdoors, no talking, no music",
    ),
    (
        "steps",
        "steps-pavement",
        "Footsteps of one person walking on a quiet paved sidewalk, hard soles, echoing slightly, no talking, no music",
    ),
    (
        "birds",
        "birds-morning",
        "Several small songbirds singing in trees at early morning, outdoors, field recording, no music",
    ),
    (
        "birds",
        "birds-crow",
        "A crow cawing a few times in a quiet park with faint wind, outdoors, no music",
    ),
    (
        "birds",
        "birds-pigeons",
        "Pigeons cooing and flapping wings on a rooftop, close, outdoors, no music",
    ),
    (
        "water",
        "water-stream",
        "A small stream flowing over stones in a forest, bubbling, outdoors, field recording, no music",
    ),
    (
        "water",
        "water-fountain",
        "A city fountain splashing steadily into a stone basin, outdoors, no music",
    ),
    (
        "water",
        "water-waves",
        "Gentle sea waves washing onto a pebble beach, rolling and receding, outdoors, no music",
    ),
    (
        "machine",
        "machine-bicycle",
        "A bicycle freewheel ticking and a bell ringing twice while riding past on a road, outdoors, no music",
    ),
    (
        "machine",
        "machine-engine",
        "A diesel engine idling steadily with a low rumble, close recording, no music",
    ),
    (
        "machine",
        "machine-fan",
        "An electric fan humming and whirring at a constant speed in a quiet room, no music",
    ),
]


def _generate(prompt: str, key: str) -> bytes:
    body = json.dumps(
        {
            "text": prompt,
            "duration_seconds": DURATION_S,
            "prompt_influence": PROMPT_INFLUENCE,
            "model_id": MODEL,
        }
    ).encode()
    req = urllib.request.Request(
        URL,
        data=body,
        headers={"xi-api-key": key, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:  # noqa: S310 - fixed https URL
            return resp.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:300]
        raise SystemExit(f"ElevenLabs HTTP {exc.code}: {detail}") from None


def _to_wav(mp3: bytes, dest: Path) -> None:
    # 48 kHz mono, matching the backend's canonical rate; peak-normalised to 0.89 like the M7 set
    proc = subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-i", "pipe:0", "-ac", "1", "-ar", "48000", str(dest)],
        input=mp3, capture_output=True, check=False,
    )  # fmt: skip
    if proc.returncode:
        raise SystemExit(f"ffmpeg failed: {proc.stderr.decode(errors='replace')[:300]}")
    normalise(dest)


def normalise(path: Path) -> None:
    """Bring a clip to about -22 dBFS RMS with a soft ceiling at 0.89, so it clears every ingest threshold."""
    x, sr = sf.read(path, dtype="float64")
    rms = float(np.sqrt(np.mean(x * x))) or 1e-9
    x = x * (10 ** (-22.0 / 20.0) / rms)
    x = np.tanh(x / 0.89) * 0.89 if np.max(np.abs(x)) > 0.89 else x
    sf.write(path, x, sr, subtype="PCM_16")


def generate(only: str | None, force: bool, pack: bool = False) -> None:
    key = os.environ.get("ELEVENLABS_API_KEY", "")
    if not key:
        raise SystemExit("set ELEVENLABS_API_KEY in the environment")
    OUT.mkdir(parents=True, exist_ok=True)
    manifest_path = OUT / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    items = [(sp.group, sp.name, PROMPTS[sp.name], sp.teach_as) for sp in SPECIMENS]
    if pack:
        items = [(g, n, p, None) for g, n, p in PACK]
    for group, name, prompt, teach_as in items:
        if only and name != only:
            continue
        dest = OUT / f"{name}.wav"
        if dest.exists() and not force:
            print(f"skip {dest.name} (exists; --force to regenerate)")
            continue
        print(f"generating {dest.name} ...", flush=True)
        _to_wav(_generate(prompt, key), dest)
        manifest[dest.name] = {
            "group": group,
            "teach_as": teach_as,
            "prompt": prompt,
            "model": MODEL,
            "duration_requested_s": DURATION_S,
            "prompt_influence": PROMPT_INFLUENCE,
            "sha256": hashlib.sha256(dest.read_bytes()).hexdigest(),
            "provenance": "AI-generated with the ElevenLabs sound-effects API; NOT a field recording",
        }
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(f"done -> {OUT}")


def renormalise_all() -> None:
    for spec in SPECIMENS:
        if (OUT / spec.filename).exists():
            normalise(OUT / spec.filename)
            print(f"normalised {spec.filename}")


def describe() -> None:
    for spec in SPECIMENS:
        print(f"{spec.filename:20} teach={spec.teach_as!s:12} {PROMPTS[spec.name]}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["generate", "describe", "normalise"])
    ap.add_argument("--only")
    ap.add_argument("--force", action="store_true")
    ap.add_argument(
        "--pack",
        action="store_true",
        help="generate the 15-clip demo pack instead of the 6-clip journey set",
    )
    a = ap.parse_args()
    {"describe": describe, "normalise": renormalise_all}.get(
        a.cmd, lambda: generate(a.only, a.force, a.pack)
    )()
