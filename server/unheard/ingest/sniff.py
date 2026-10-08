"""Container detection from magic bytes.

Client MIME types and filename extensions are hints only; this is what we trust.
"""

from __future__ import annotations

from dataclasses import dataclass

SUPPORTED_CONTAINERS: dict[str, str] = {
    "wav": "audio/wav",
    "webm": "audio/webm",
    "mp4": "audio/mp4",
    "ogg": "audio/ogg",
    "flac": "audio/flac",
    "mp3": "audio/mpeg",
}


@dataclass(frozen=True)
class Sniff:
    container: str
    mime: str
    extension: str


def sniff_container(head: bytes) -> Sniff | None:
    """Return the container implied by the first bytes, or None if unknown."""
    if len(head) < 12:
        return None
    if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
        return Sniff("wav", "audio/wav", "wav")
    if head[:4] == b"\x1a\x45\xdf\xa3":  # EBML (webm / matroska)
        return Sniff("webm", "audio/webm", "webm")
    if head[4:8] == b"ftyp":  # ISO BMFF (mp4 / m4a / 3gp)
        return Sniff("mp4", "audio/mp4", "m4a")
    if head[:4] == b"OggS":
        return Sniff("ogg", "audio/ogg", "ogg")
    if head[:4] == b"fLaC":
        return Sniff("flac", "audio/flac", "flac")
    if head[:3] == b"ID3" or (head[0] == 0xFF and (head[1] & 0xE6) == 0xE2):
        # ID3v2 tag or an MPEG audio frame sync (11 set bits + layer bits)
        return Sniff("mp3", "audio/mpeg", "mp3")
    return None
