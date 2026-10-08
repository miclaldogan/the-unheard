"""Upload → validated, decoded, canonical PCM → committed recording (durability first).

Order of operations (doc 02 "Guarantees"):
1. sniff container, size check
2. decode to canonical mono float at the canonical rate
3. validate signal (duration, silence, NaN...) — rejected uploads leave no row/file
4. hash canonical PCM; duplicate → 409 with existing id
5. write source file + canonical WAV atomically, insert recording/audio_asset rows,
   enqueue the DSP job and append ``RecordingCaptured`` in ONE transaction
"""

from __future__ import annotations

import hashlib
import io
import logging
from dataclasses import dataclass
from typing import Any

import numpy as np
import soundfile as sf

from unheard.config import Settings
from unheard.errors import AudioEmpty, AudioTooLarge, AudioUnsupportedFormat, DuplicateRecording
from unheard.events import RECORDING_CAPTURED
from unheard.ingest.decode import Decoder
from unheard.ingest.sniff import sniff_container
from unheard.ingest.validate import Limits, validate_decoded
from unheard.storage.blobs import BlobStore
from unheard.storage.db import Database
from unheard.storage.ids import uuid7
from unheard.storage.repos import AudioAssetRepo, EventRepo, JobRepo, RecordingRepo

log = logging.getLogger(__name__)

DSP_STAGE = "dsp"


@dataclass(frozen=True)
class IngestResult:
    recording_id: str
    duplicate: bool
    duration_s: float
    quality: dict[str, Any]


def canonical_wav_bytes(samples: np.ndarray, sr: int) -> bytes:
    """Canonical artefact: WAV, mono, float32 PCM at ``sr`` (lossless w.r.t. the decoder output)."""
    buf = io.BytesIO()
    sf.write(buf, samples.astype(np.float32), sr, format="WAV", subtype="FLOAT")
    return buf.getvalue()


class IngestService:
    def __init__(
        self, settings: Settings, db: Database, blobs: BlobStore, decoder: Decoder
    ) -> None:
        self.settings = settings
        self.db = db
        self.blobs = blobs
        self.decoder = decoder
        self.limits = Limits(
            min_duration_s=settings.min_duration_s,
            max_duration_s=settings.max_duration_s,
            min_source_sample_rate=settings.min_source_sample_rate,
            max_source_sample_rate=settings.max_source_sample_rate,
            silence_dbfs=settings.silence_dbfs,
            clipping_peak=settings.clipping_peak,
            clipping_flag_ratio=settings.clipping_flag_ratio,
        )

    def ingest(
        self,
        data: bytes,
        *,
        original_filename: str | None,
        client_mime: str | None,
        captured_at: str | None = None,
        device_info: dict[str, Any] | None = None,
    ) -> IngestResult:
        if not data:
            raise AudioEmpty("upload is empty")
        if len(data) > self.settings.max_upload_bytes:
            raise AudioTooLarge(
                f"upload is {len(data)} bytes; limit is {self.settings.max_upload_bytes}",
                extra={"limit_bytes": self.settings.max_upload_bytes},
            )
        sniff = sniff_container(data[:64])
        if sniff is None:
            raise AudioUnsupportedFormat(
                "could not recognise the audio container from its contents "
                "(supported: wav, webm, mp4/m4a, ogg, flac, mp3)",
                extra={"client_mime": client_mime},
            )

        sr = self.settings.canonical_sample_rate
        decoded = self.decoder.decode(data, sniff.container, sr)
        samples, quality = validate_decoded(
            decoded.samples, sr, decoded.source.sample_rate, decoded.source.channels, self.limits
        )
        quality["decoder"] = decoded.decoder
        quality["source_duration_s"] = decoded.source.duration_s

        canonical = canonical_wav_bytes(samples, sr)
        content_hash = hashlib.sha256(samples.astype(np.float32).tobytes()).hexdigest()
        source_hash = hashlib.sha256(data).hexdigest()
        duration_s = samples.size / sr

        with self.db.connection() as conn:
            existing = RecordingRepo.get_by_hash(conn, content_hash)
        if existing is not None:
            raise DuplicateRecording(
                "an identical recording already exists",
                extra={"recording_id": existing.id},
            )

        rid = uuid7()
        src_rel = self.blobs.relative_path("audio", rid, f"source.{sniff.extension}")
        can_rel = self.blobs.relative_path("audio", rid, "canonical.wav")
        self.blobs.write_atomic(src_rel, data)
        self.blobs.write_atomic(can_rel, canonical)
        try:
            with self.db.transaction() as conn:
                RecordingRepo.insert(
                    conn,
                    id=rid,
                    content_hash=content_hash,
                    source_hash=source_hash,
                    duration_s=duration_s,
                    quality=quality,
                    original_filename=_safe_name(original_filename),
                    client_mime=client_mime,
                    captured_at=captured_at,
                    device_info=device_info,
                )
                AudioAssetRepo.insert(
                    conn,
                    recording_id=rid,
                    kind="source",
                    path=src_rel,
                    container=sniff.container,
                    codec=decoded.source.codec,
                    sample_rate=decoded.source.sample_rate,
                    channels=decoded.source.channels,
                    sample_format=decoded.source.sample_format,
                    nbytes=len(data),
                )
                AudioAssetRepo.insert(
                    conn,
                    recording_id=rid,
                    kind="canonical",
                    path=can_rel,
                    container="wav",
                    codec="pcm_f32le",
                    sample_rate=sr,
                    channels=1,
                    sample_format="flt",
                    nbytes=len(canonical),
                )
                JobRepo.enqueue(conn, rid, DSP_STAGE)
                EventRepo.append(
                    conn,
                    RECORDING_CAPTURED,
                    {"content_hash": content_hash, "duration_s": duration_s, "quality": quality},
                    recording_id=rid,
                )
        except Exception:
            # roll back the files so a failed insert leaves nothing behind
            self.blobs.delete_recording_dirs(rid)
            raise
        log.info("recording %s captured (%.2f s, %s)", rid, duration_s, sniff.container)
        return IngestResult(
            recording_id=rid, duplicate=False, duration_s=duration_s, quality=quality
        )


def _safe_name(name: str | None) -> str | None:
    """Keep only a display-safe basename for metadata; never used for paths."""
    if not name:
        return None
    base = name.replace("\\", "/").split("/")[-1]
    return base[:200] or None
