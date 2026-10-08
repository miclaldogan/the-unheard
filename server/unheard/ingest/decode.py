"""Decoding uploads to canonical PCM.

Primary decoder: ffmpeg (``-nostdin``, timeout, bytes via stdin, filenames never used).
Fallback for WAV/FLAC/OGG only: libsndfile through ``soundfile`` plus SciPy resampling,
used when ffmpeg is not installed.

Output: mono float64 array at the canonical rate, plus probed source metadata.
``DecodedAudio.samples`` is the *decoded* signal (no gain applied); only resampling and
channel averaging are performed (doc 03 §1). Clipping/silence are measured by the caller.
"""

from __future__ import annotations

import io
import json
import logging
import shutil
import subprocess
from dataclasses import dataclass
from math import gcd

import numpy as np
from numpy.typing import NDArray

from unheard.errors import AudioUndecodable, DecoderUnavailable

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class SourceInfo:
    codec: str | None
    sample_rate: int
    channels: int
    sample_format: str | None
    duration_s: float | None


@dataclass(frozen=True)
class DecodedAudio:
    samples: NDArray[np.float64]  # mono, canonical rate, float64 in [-1, 1] nominal
    sample_rate: int
    source: SourceInfo
    decoder: str


class Decoder:
    def __init__(
        self,
        *,
        ffmpeg_bin: str = "ffmpeg",
        ffprobe_bin: str = "ffprobe",
        timeout_s: float = 30.0,
    ) -> None:
        self.ffmpeg_bin = ffmpeg_bin
        self.ffprobe_bin = ffprobe_bin
        self.timeout_s = timeout_s

    # -- capability ---------------------------------------------------------
    def ffmpeg_available(self) -> bool:
        return (
            shutil.which(self.ffmpeg_bin) is not None and shutil.which(self.ffprobe_bin) is not None
        )

    def ffmpeg_version(self) -> str | None:
        if not self.ffmpeg_available():
            return None
        try:
            out = subprocess.run(
                [self.ffmpeg_bin, "-version"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            return out.stdout.splitlines()[0] if out.stdout else None
        except (OSError, subprocess.SubprocessError):
            return None

    # -- public -------------------------------------------------------------
    def decode(self, data: bytes, container: str, target_rate: int) -> DecodedAudio:
        if self.ffmpeg_available():
            return self._decode_ffmpeg(data, container, target_rate)
        if container in {"wav", "flac", "ogg"}:
            return self._decode_soundfile(data, target_rate)
        raise DecoderUnavailable(
            f"ffmpeg is required to decode '{container}' uploads but was not found on PATH"
        )

    # -- ffmpeg -------------------------------------------------------------
    def _probe(self, data: bytes) -> SourceInfo:
        cmd = [
            self.ffprobe_bin,
            "-v",
            "error",
            "-hide_banner",
            "-show_entries",
            "stream=codec_type,codec_name,sample_rate,channels,sample_fmt:format=duration",
            "-of",
            "json",
            "-i",
            "pipe:0",
        ]
        try:
            res = subprocess.run(
                cmd, input=data, capture_output=True, timeout=self.timeout_s, check=False
            )
        except subprocess.TimeoutExpired as e:
            raise AudioUndecodable("ffprobe timed out") from e
        if res.returncode != 0:
            raise AudioUndecodable(
                "ffprobe could not parse the file: "
                f"{res.stderr.decode(errors='replace').strip()[:300]}"
            )
        try:
            info = json.loads(res.stdout.decode())
        except json.JSONDecodeError as e:
            raise AudioUndecodable("ffprobe returned unreadable output") from e
        audio_streams = [s for s in info.get("streams", []) if s.get("codec_type") == "audio"]
        if not audio_streams:
            raise AudioUndecodable("file contains no audio stream")
        s = audio_streams[0]
        dur = info.get("format", {}).get("duration")
        try:
            sr = int(s.get("sample_rate") or 0)
            ch = int(s.get("channels") or 0)
        except (TypeError, ValueError) as e:
            raise AudioUndecodable("audio stream has invalid sample rate/channels") from e
        return SourceInfo(
            codec=s.get("codec_name"),
            sample_rate=sr,
            channels=ch,
            sample_format=s.get("sample_fmt"),
            duration_s=float(dur) if dur not in (None, "N/A") else None,
        )

    def _decode_ffmpeg(self, data: bytes, container: str, target_rate: int) -> DecodedAudio:
        src = self._probe(data)
        # Explicit equal-weight downmix (mean of channels). ffmpeg's default stereo->mono
        # matrix applies 1/sqrt(2) gains, which would change the RMS by +3 dB.
        n_ch = max(1, src.channels)
        weights = "+".join(f"{1.0 / n_ch:.6f}*c{i}" for i in range(n_ch))
        cmd = [
            self.ffmpeg_bin,
            "-nostdin",
            "-v",
            "error",
            "-hide_banner",
            "-i",
            "pipe:0",
            "-vn",
            "-sn",
            "-dn",
            "-map",
            "0:a:0",
            "-af",
            f"pan=mono|c0={weights},aresample=resampler=swr:dither_method=none",
            "-ar",
            str(target_rate),
            "-f",
            "f32le",
            "-acodec",
            "pcm_f32le",
            "pipe:1",
        ]
        try:
            res = subprocess.run(
                cmd, input=data, capture_output=True, timeout=self.timeout_s, check=False
            )
        except subprocess.TimeoutExpired as e:
            raise AudioUndecodable("ffmpeg timed out while decoding") from e
        if res.returncode != 0:
            raise AudioUndecodable(
                f"ffmpeg failed: {res.stderr.decode(errors='replace').strip()[:300]}"
            )
        if len(res.stdout) % 4 != 0:
            raise AudioUndecodable("ffmpeg produced a truncated PCM stream")
        samples = np.frombuffer(res.stdout, dtype="<f4").astype(np.float64)
        return DecodedAudio(samples=samples, sample_rate=target_rate, source=src, decoder="ffmpeg")

    # -- soundfile fallback ---------------------------------------------------
    def _decode_soundfile(self, data: bytes, target_rate: int) -> DecodedAudio:
        import soundfile as sf

        try:
            with sf.SoundFile(io.BytesIO(data)) as f:
                sr = int(f.samplerate)
                ch = int(f.channels)
                subtype = f.subtype
                arr = f.read(dtype="float64", always_2d=True)
        except Exception as e:  # libsndfile raises RuntimeError/sf.LibsndfileError
            raise AudioUndecodable(f"libsndfile could not decode the file: {e}") from e
        if sr <= 0 or ch <= 0:
            raise AudioUndecodable("invalid sample rate or channel count")
        mono = downmix(arr)
        if sr != target_rate:
            mono = resample_poly(mono, sr, target_rate)
        return DecodedAudio(
            samples=mono,
            sample_rate=target_rate,
            source=SourceInfo(
                codec=subtype,
                sample_rate=sr,
                channels=ch,
                sample_format=subtype,
                duration_s=arr.shape[0] / sr,
            ),
            decoder="soundfile",
        )


def downmix(frames: NDArray[np.float64]) -> NDArray[np.float64]:
    """(n, channels) -> (n,) by averaging channels (what ffmpeg ``-ac 1`` does)."""
    if frames.ndim == 1:
        return frames.astype(np.float64)
    return frames.mean(axis=1, dtype=np.float64)


def resample_poly(x: NDArray[np.float64], sr_in: int, sr_out: int) -> NDArray[np.float64]:
    from scipy.signal import resample_poly as _rp

    g = gcd(sr_in, sr_out)
    y: NDArray[np.float64] = _rp(x, sr_out // g, sr_in // g)
    return np.asarray(y, dtype=np.float64)
