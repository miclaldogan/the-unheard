from __future__ import annotations

from tests.fixtures import synth
from unheard.ingest.sniff import sniff_container


def test_wav_and_flac_detected() -> None:
    x = synth.sine(440, 16000, 0.1)
    assert sniff_container(synth.wav_bytes(x, 16000)[:64]).container == "wav"
    assert sniff_container(synth.flac_bytes(x, 16000)[:64]).container == "flac"


def test_magic_bytes_table() -> None:
    assert sniff_container(b"\x1a\x45\xdf\xa3" + b"\0" * 20).container == "webm"
    assert sniff_container(b"\0\0\0\x20ftypM4A " + b"\0" * 20).container == "mp4"
    assert sniff_container(b"OggS" + b"\0" * 20).container == "ogg"
    assert sniff_container(b"ID3" + b"\0" * 20).container == "mp3"
    assert sniff_container(b"\xff\xfb\x90\x00" + b"\0" * 20).container == "mp3"


def test_unknown_and_short() -> None:
    assert sniff_container(b"hello world, not audio") is None
    assert sniff_container(b"RIFF") is None
    assert sniff_container(b"%PDF-1.4" + b"\0" * 20) is None
