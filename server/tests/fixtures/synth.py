"""Deterministic synthetic signals for DSP and ingest tests (never committed as files)."""

from __future__ import annotations

import io
import subprocess

import numpy as np
import soundfile as sf
from numpy.typing import NDArray


def sine(
    freq: float, sr: int, duration: float, amp: float = 0.5, phase: float = 0.0
) -> NDArray[np.float64]:
    t = np.arange(int(round(duration * sr))) / sr
    return amp * np.sin(2 * np.pi * freq * t + phase)


def multi_sine(
    freqs: list[float], sr: int, duration: float, amp: float = 0.2
) -> NDArray[np.float64]:
    return sum(sine(f, sr, duration, amp) for f in freqs)


def silence(sr: int, duration: float) -> NDArray[np.float64]:
    return np.zeros(int(round(duration * sr)))


def white_noise(
    sr: int, duration: float, amp: float = 0.1, seed: int = 1234
) -> NDArray[np.float64]:
    rng = np.random.default_rng(seed)
    return amp * rng.standard_normal(int(round(duration * sr)))


def click_train(
    rate_hz: float, sr: int, duration: float, amp: float = 0.9, width: int = 8
) -> NDArray[np.float64]:
    x = np.zeros(int(round(duration * sr)))
    period = int(round(sr / rate_hz))
    for start in range(0, x.size, period):
        x[start : start + width] = amp
    return x


def clipped_sine(freq: float, sr: int, duration: float, gain: float = 3.0) -> NDArray[np.float64]:
    return np.clip(sine(freq, sr, duration, amp=gain), -1.0, 1.0)


def stereo(left: NDArray[np.float64], right: NDArray[np.float64]) -> NDArray[np.float64]:
    return np.stack([left, right], axis=1)


def wav_bytes(x: NDArray[np.float64], sr: int, subtype: str = "PCM_16") -> bytes:
    buf = io.BytesIO()
    sf.write(buf, x, sr, format="WAV", subtype=subtype)
    return buf.getvalue()


def flac_bytes(x: NDArray[np.float64], sr: int) -> bytes:
    buf = io.BytesIO()
    sf.write(buf, x, sr, format="FLAC")
    return buf.getvalue()


def ffmpeg_encode(wav: bytes, container: str, codec: str, extra: list[str] | None = None) -> bytes:
    """Encode WAV bytes with ffmpeg to e.g. webm/libopus or mp4/aac (what browsers send)."""
    cmd = [
        "ffmpeg",
        "-nostdin",
        "-v",
        "error",
        "-i",
        "pipe:0",
        "-c:a",
        codec,
        *(extra or []),
        "-f",
        container,
        "pipe:1",
    ]
    res = subprocess.run(cmd, input=wav, capture_output=True, timeout=60, check=False)
    if res.returncode != 0:
        raise RuntimeError(res.stderr.decode(errors="replace"))
    return res.stdout


def environmental_like(sr: int, duration: float, seed: int = 7) -> NDArray[np.float64]:
    """Wind-ish low noise + a 'bird' chirp + three clicks: a realistic mixed test signal."""
    rng = np.random.default_rng(seed)
    n = int(round(duration * sr))
    t = np.arange(n) / sr
    noise = rng.standard_normal(n)
    # cheap low-pass: moving average
    k = 64
    noise = np.convolve(noise, np.ones(k) / k, mode="same") * 0.6
    chirp = (
        0.3
        * np.sin(2 * np.pi * (2500 + 800 * np.sin(2 * np.pi * 3 * t)) * t)
        * (t > 1.0)
        * (t < 2.0)
    )
    clicks = np.zeros(n)
    for s in (0.5, 2.5, 3.5):
        i = int(s * sr)
        clicks[i : i + 10] = 0.8
    return np.clip(noise + chirp + clicks, -1, 1)
