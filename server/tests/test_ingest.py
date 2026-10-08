"""Ingest-level tests: decode, validate, canonicalise, persist (no HTTP)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from tests.conftest import HAS_FFMPEG, make_settings, requires_ffmpeg
from tests.fixtures import synth
from unheard.api.deps import Services
from unheard.errors import (
    AudioEmpty,
    AudioSilent,
    AudioTooLarge,
    AudioTooLong,
    AudioTooShort,
    AudioUndecodable,
    AudioUnsupportedFormat,
    DecoderUnavailable,
    DuplicateRecording,
)
from unheard.ingest.decode import Decoder
from unheard.ingest.validate import Limits, validate_decoded
from unheard.storage.repos import AudioAssetRepo, EventRepo, JobRepo, RecordingRepo


@pytest.fixture
def services(tmp_path: Path):
    s = Services.build(make_settings(tmp_path))
    yield s
    s.close()


@pytest.mark.parametrize(
    "sr,channels", [(16_000, 1), (44_100, 1), (48_000, 1), (44_100, 2), (48_000, 2)]
)
def test_inputs_normalised_to_48k_mono(services: Services, sr: int, channels: int) -> None:
    x = synth.sine(1000.0, sr, 3.5, amp=0.4)
    data = synth.wav_bytes(synth.stereo(x, x) if channels == 2 else x, sr)
    r = services.ingest.ingest(data, original_filename="t.wav", client_mime="audio/wav")
    with services.db.connection() as conn:
        rec = RecordingRepo.get(conn, r.recording_id)
        canonical = AudioAssetRepo.get(conn, r.recording_id, "canonical")
        source = AudioAssetRepo.get(conn, r.recording_id, "source")
        jobs = JobRepo.for_recording(conn, r.recording_id)
        events = EventRepo.for_recording(conn, r.recording_id)
    assert rec is not None and rec.status == "uploaded"
    assert canonical and canonical.sample_rate == 48_000 and canonical.channels == 1
    assert source and source.sample_rate == sr and source.channels == channels
    y, csr = sf.read(services.blobs.absolute(canonical.path))
    assert csr == 48_000 and y.ndim == 1
    assert abs(y.size / 48_000 - 3.5) < 0.01
    # resampling keeps RMS (0.4/√2) within 1 %
    assert np.sqrt(np.mean(y**2)) == pytest.approx(0.4 / np.sqrt(2), rel=0.01)
    assert jobs and jobs[0].stage == "dsp" and jobs[0].status == "queued"
    assert [e["type"] for e in events] == ["RecordingCaptured"]


def test_rejections_leave_no_row_or_file(services: Services) -> None:
    sr = 48_000
    cases = [
        (b"", AudioEmpty),
        (b"not audio at all" * 10, AudioUnsupportedFormat),
        (synth.wav_bytes(synth.sine(440, sr, 1.0), sr), AudioTooShort),
        (synth.wav_bytes(synth.sine(440, sr, 31.0), sr), AudioTooLong),
        (synth.wav_bytes(synth.silence(sr, 4.0), sr), AudioSilent),
        (synth.wav_bytes(synth.sine(440, sr, 4.0, amp=1e-4), sr), AudioSilent),  # -83 dBFS
        (b"RIFF\x00\x00\x00\x00WAVEjunkjunkjunk" + b"\x01" * 100, AudioUndecodable),
    ]
    for data, exc in cases:
        with pytest.raises(exc):
            services.ingest.ingest(data, original_filename="x", client_mime=None)
    with services.db.connection() as conn:
        assert RecordingRepo.count(conn) == 0
    assert (
        not list((services.settings.data_dir / "audio").rglob("*"))
        if (services.settings.data_dir / "audio").exists()
        else True
    )


def test_oversized_upload(tmp_path: Path) -> None:
    s = Services.build(make_settings(tmp_path, max_upload_bytes=1000))
    try:
        with pytest.raises(AudioTooLarge):
            s.ingest.ingest(b"\0" * 1001, original_filename=None, client_mime=None)
    finally:
        s.close()


def test_duplicate_upload_is_409_with_existing_id(services: Services) -> None:
    data = synth.wav_bytes(synth.sine(440, 48_000, 3.0), 48_000)
    first = services.ingest.ingest(data, original_filename="a.wav", client_mime=None)
    with pytest.raises(DuplicateRecording) as ei:
        services.ingest.ingest(data, original_filename="b.wav", client_mime=None)
    assert ei.value.extra["recording_id"] == first.recording_id


def test_clipping_is_flagged_not_rejected(services: Services) -> None:
    data = synth.wav_bytes(synth.clipped_sine(440, 48_000, 3.0), 48_000)
    r = services.ingest.ingest(data, original_filename=None, client_mime=None)
    assert "clipping" in r.quality["flags"]
    assert r.quality["clipping_ratio"] > 0.5


def test_mime_and_extension_are_not_trusted(services: Services) -> None:
    data = synth.flac_bytes(synth.sine(440, 48_000, 3.0), 48_000)
    r = services.ingest.ingest(data, original_filename="lies.wav", client_mime="audio/wav")
    with services.db.connection() as conn:
        src = AudioAssetRepo.get(conn, r.recording_id, "source")
    assert src is not None and src.container == "flac" and src.path.endswith("source.flac")


def test_validate_sanitises_nan() -> None:
    limits = Limits(3.0, 30.0, 8000, 192000, -60.0, 0.99, 0.005)
    x = synth.sine(440, 48_000, 3.0)
    x[10] = np.nan
    x[11] = np.inf
    clean, q = validate_decoded(x, 48_000, 48_000, 1, limits)
    assert np.all(np.isfinite(clean)) and q["non_finite_samples_replaced"] == 2
    assert "non_finite_samples" in q["flags"]


@requires_ffmpeg
@pytest.mark.parametrize(
    "container,codec,ext",
    [
        ("webm", "libopus", "webm"),
        ("mp4", "aac", "m4a"),
        ("ogg", "libvorbis", "ogg"),
        ("mp3", "libmp3lame", "mp3"),
    ],
)
def test_browser_codecs_decode(services: Services, container: str, codec: str, ext: str) -> None:
    """What MediaRecorder actually produces: webm/opus (Chrome/Firefox), mp4/aac (Safari)."""
    wav = synth.wav_bytes(synth.sine(1000.0, 48_000, 4.0, amp=0.3), 48_000)
    try:
        enc = synth.ffmpeg_encode(
            wav,
            container,
            codec,
            ["-movflags", "frag_keyframe+empty_moov"] if container == "mp4" else [],
        )
    except RuntimeError as e:
        pytest.skip(f"encoder {codec} unavailable: {e}")
    r = services.ingest.ingest(enc, original_filename=f"rec.{ext}", client_mime=None)
    with services.db.connection() as conn:
        src = AudioAssetRepo.get(conn, r.recording_id, "source")
        can = AudioAssetRepo.get(conn, r.recording_id, "canonical")
    assert src is not None and src.container == container
    assert can is not None and can.sample_rate == 48_000
    # lossy codecs change level slightly; duration within 100 ms, RMS within 10 %
    assert abs(r.duration_s - 4.0) < 0.1
    y, _ = sf.read(services.blobs.absolute(can.path))
    assert np.sqrt(np.mean(y**2)) == pytest.approx(0.3 / np.sqrt(2), rel=0.1)


def test_soundfile_fallback_when_ffmpeg_missing(tmp_path: Path) -> None:
    dec = Decoder(ffmpeg_bin="/nonexistent/ffmpeg", ffprobe_bin="/nonexistent/ffprobe")
    assert not dec.ffmpeg_available()
    x = synth.sine(1000.0, 44_100, 3.0, amp=0.4)
    out = dec.decode(synth.wav_bytes(synth.stereo(x, x), 44_100), "wav", 48_000)
    assert out.decoder == "soundfile" and out.sample_rate == 48_000
    assert out.samples.ndim == 1 and abs(out.samples.size / 48_000 - 3.0) < 0.01
    assert np.sqrt(np.mean(out.samples**2)) == pytest.approx(0.4 / np.sqrt(2), rel=0.01)
    with pytest.raises(DecoderUnavailable):
        dec.decode(b"\x1a\x45\xdf\xa3" + b"\0" * 100, "webm", 48_000)


@pytest.mark.skipif(not HAS_FFMPEG, reason="compares ffmpeg and soundfile paths")
def test_ffmpeg_and_soundfile_agree_on_wav(tmp_path: Path) -> None:
    x = synth.environmental_like(48_000, 3.0)
    data = synth.wav_bytes(x, 48_000, subtype="FLOAT")
    a = Decoder().decode(data, "wav", 48_000).samples
    b = Decoder(ffmpeg_bin="/nope", ffprobe_bin="/nope").decode(data, "wav", 48_000).samples
    np.testing.assert_allclose(a, b, atol=1e-6)
