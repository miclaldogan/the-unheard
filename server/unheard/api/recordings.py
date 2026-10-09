"""Recording endpoints. Thin handlers: validation + delegation to services/repos."""

from __future__ import annotations

import json
from typing import Any, Literal

import numpy as np
from fastapi import APIRouter, Depends, File, Form, Query, Response, UploadFile
from fastapi.responses import FileResponse

from unheard.api.deps import Services, get_services, require_token, valid_recording_id
from unheard.api.schemas import (
    AssetInfo,
    ErrorInfo,
    FeatureSeries,
    FeaturesResponse,
    InferenceInfo,
    JobInfo,
    RecordingDetail,
    RecordingList,
    RecordingSummary,
    SpectrogramResponse,
    UploadAccepted,
    WaveformSummary,
)
from unheard.errors import NotFound, NotReady, ValidationFailed
from unheard.events import RECORDING_DELETED
from unheard.ingest.service import DSP_STAGE
from unheard.models.contracts import InferenceResult
from unheard.storage.repos import (
    AudioAssetRepo,
    EventRepo,
    FeatureSetRepo,
    JobRepo,
    RecordingRepo,
    RecordingRow,
)
from unheard.storage.repos_m2 import AnnotationRepo, PredictionRepo

router = APIRouter(dependencies=[Depends(require_token)])


def _links(rid: str) -> dict[str, str]:
    base = f"/api/recordings/{rid}"
    return {
        "self": base,
        "audio": f"{base}/audio",
        "canonical_audio": f"{base}/audio?variant=canonical",
        "features": f"{base}/features",
        "spectrogram": f"{base}/spectrogram",
    }


def _summary(rec: RecordingRow, dsp_version: int | None) -> RecordingSummary:
    return RecordingSummary(
        id=rec.id,
        created_at=rec.created_at,
        captured_at=rec.captured_at,
        original_filename=rec.original_filename,
        duration_s=rec.duration_s,
        status=rec.status,  # type: ignore[arg-type]
        quality=rec.quality,
        error=ErrorInfo(**rec.error) if rec.error else None,
        dsp_version=dsp_version,
    )


def _inference_info(services: Services, rid: str) -> InferenceInfo:
    """Model-adapter contract view: persisted base prediction + pooled embedding, or not_run."""
    from unheard.storage.repos_m2 import EmbeddingRepo, ModelVersionRepo

    with services.db.connection() as conn:
        base = PredictionRepo.latest(conn, rid, "base")
        if base is None:
            return InferenceInfo(**InferenceResult.not_run().to_json())  # type: ignore[arg-type]
        mv = ModelVersionRepo.get(conn, base.model_version_id)
        emb = EmbeddingRepo.pooled(conn, rid, base.model_version_id)
    return InferenceInfo(
        status="ok",
        model_id=mv.name if mv else None,
        model_version=mv.revision if mv else None,
        predictions=[
            {"label": c["name"], "score": c["similarity"], "score_kind": "cosine_similarity"}
            for c in base.results[:5]
        ],
        embedding={"dim": int(emb.vec.size), "window_idx": None} if emb else None,
        error=None,
    )


def _get_or_404(services: Services, rid: str) -> RecordingRow:
    with services.db.connection() as conn:
        rec = RecordingRepo.get(conn, rid)
    if rec is None:
        raise NotFound("recording not found")
    return rec


@router.post("/recordings", response_model=UploadAccepted, status_code=202)
async def upload_recording(
    file: UploadFile = File(...),
    captured_at: str | None = Form(default=None),
    device_info: str | None = Form(default=None),
    services: Services = Depends(get_services),
) -> UploadAccepted:
    limit = services.settings.max_upload_bytes
    data = await file.read(limit + 1)
    device: dict[str, Any] | None = None
    if device_info:
        try:
            parsed = json.loads(device_info)
        except json.JSONDecodeError as e:
            raise ValidationFailed("device_info must be JSON") from e
        if not isinstance(parsed, dict):
            raise ValidationFailed("device_info must be a JSON object")
        device = parsed
    result = services.ingest.ingest(
        data,
        original_filename=file.filename,
        client_mime=file.content_type,
        captured_at=captured_at,
        device_info=device,
    )
    return UploadAccepted(
        recording_id=result.recording_id,
        status="uploaded",
        duration_s=result.duration_s,
        quality=result.quality,
        links=_links(result.recording_id),
    )


@router.get("/recordings", response_model=RecordingList)
def list_recordings(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    services: Services = Depends(get_services),
) -> RecordingList:
    with services.db.connection() as conn:
        rows = RecordingRepo.list(conn, limit=limit, offset=offset)
        total = RecordingRepo.count(conn)
        items = []
        for r in rows:
            fs = FeatureSetRepo.latest(conn, r.id)
            items.append(_summary(r, fs.dsp_version if fs else None))
    return RecordingList(items=items, total=total, limit=limit, offset=offset)


@router.get("/recordings/{recording_id}", response_model=RecordingDetail)
def get_recording(
    recording_id: str = Depends(valid_recording_id),
    services: Services = Depends(get_services),
) -> RecordingDetail:
    rec = _get_or_404(services, recording_id)
    with services.db.connection() as conn:
        assets = AudioAssetRepo.for_recording(conn, rec.id)
        jobs = JobRepo.for_recording(conn, rec.id)
        fs = FeatureSetRepo.latest(conn, rec.id)
    base = _summary(rec, fs.dsp_version if fs else None)
    return RecordingDetail(
        **base.model_dump(),
        content_hash=rec.content_hash,
        source_hash=rec.source_hash,
        client_mime=rec.client_mime,
        device_info=rec.device_info,
        assets=[
            AssetInfo(
                kind=a.kind,  # type: ignore[arg-type]
                container=a.container,
                codec=a.codec,
                sample_rate=a.sample_rate,
                channels=a.channels,
                sample_format=a.sample_format,
                bytes=a.bytes,
            )
            for a in assets
        ],
        jobs=[
            JobInfo(
                id=j.id,
                stage=j.stage,
                status=j.status,  # type: ignore[arg-type]
                attempts=j.attempts,
                error=j.error,
                updated_at=j.updated_at,
            )
            for j in jobs
        ],
        features=fs.summary if fs else None,
        inference=_inference_info(services, rec.id),
        links=_links(rec.id),
    )


@router.get("/recordings/{recording_id}/audio")
def get_audio(
    variant: Literal["source", "canonical"] = Query(default="source"),
    recording_id: str = Depends(valid_recording_id),
    services: Services = Depends(get_services),
) -> FileResponse:
    rec = _get_or_404(services, recording_id)
    with services.db.connection() as conn:
        asset = AudioAssetRepo.get(conn, rec.id, variant)
    if asset is None:
        raise NotFound("audio asset not found")
    path = services.blobs.absolute(asset.path)
    if not path.is_file():
        raise NotFound("audio file missing on disk")
    media = {
        "wav": "audio/wav",
        "webm": "audio/webm",
        "mp4": "audio/mp4",
        "ogg": "audio/ogg",
        "flac": "audio/flac",
        "mp3": "audio/mpeg",
    }.get(asset.container or "", "application/octet-stream")
    return FileResponse(
        path,
        media_type=media,
        filename=path.name,
        headers={"Cache-Control": "private, max-age=3600"},
    )


def _load_features(
    services: Services, rid: str
) -> tuple[int, str, dict[str, Any], dict[str, np.ndarray]]:
    rec = _get_or_404(services, rid)
    with services.db.connection() as conn:
        fs = FeatureSetRepo.latest(conn, rec.id)
    if fs is None:
        if rec.status == "failed":
            raise NotReady("processing failed for this recording", extra={"error": rec.error})
        raise NotReady("features are not ready yet", extra={"status": rec.status})
    path = services.blobs.absolute(fs.artifact_path)
    if not path.is_file():
        raise NotFound("feature artifact missing on disk")
    with np.load(path) as z:
        arrays = {k: z[k] for k in z.files}
    return fs.dsp_version, fs.artifact_sha256, fs.summary, arrays


def _f(a: np.ndarray) -> list[float]:
    return [float(v) for v in np.asarray(a, dtype=np.float64).tolist()]


@router.get("/recordings/{recording_id}/features", response_model=FeaturesResponse)
def get_features(
    recording_id: str = Depends(valid_recording_id),
    services: Services = Depends(get_services),
) -> FeaturesResponse:
    version, sha, summary, a = _load_features(services, recording_id)
    return FeaturesResponse(
        recording_id=recording_id,
        dsp_version=version,
        artifact_sha256=sha,
        summary=summary,
        waveform=WaveformSummary(
            buckets=int(a["wave_min"].size),
            duration_s=float(summary["duration_s"]),
            min=_f(a["wave_min"]),
            max=_f(a["wave_max"]),
            rms=_f(a["wave_rms"]),
        ),
        series=FeatureSeries(
            times_s=_f(a["times_s"]),
            rms_envelope_db=_f(a["rms_envelope_db"]),
            centroid_hz=_f(a["centroid_hz"]),
            bandwidth_hz=_f(a["bandwidth_hz"]),
            rolloff_hz=_f(a["rolloff_hz"]),
            flatness=_f(a["flatness"]),
            flux=_f(a["flux"]),
        ),
        onset_strength=_f(a["onset_strength"]),
        onset_times_s=_f(a["onset_times_s"]),
    )


def _pool_frames(
    values: np.ndarray, times: np.ndarray, max_frames: int
) -> tuple[np.ndarray, np.ndarray, int]:
    n = values.shape[1]
    if n <= max_frames:
        return values, times, 1
    factor = int(np.ceil(n / max_frames))
    n_out = n // factor
    trimmed = values[:, : n_out * factor].reshape(values.shape[0], n_out, factor)
    pooled = trimmed.mean(axis=2)
    t = times[: n_out * factor].reshape(n_out, factor)[:, 0]
    return pooled, t, factor


@router.get("/recordings/{recording_id}/spectrogram", response_model=SpectrogramResponse)
def get_spectrogram(
    kind: Literal["mel", "stft"] = Query(default="mel"),
    max_frames: int = Query(default=1024, ge=16, le=8192),
    recording_id: str = Depends(valid_recording_id),
    services: Services = Depends(get_services),
) -> SpectrogramResponse:
    version, _sha, summary, a = _load_features(services, recording_id)
    if kind == "mel":
        values, times, freqs = a["log_mel_db"], a["mel_times_s"], a["mel_freqs_hz"]
    else:
        values, times, freqs = a["stft_view_db"], a["times_s"], a["stft_view_freqs_hz"]
    values = np.asarray(values, dtype=np.float64)
    pooled, t, factor = _pool_frames(values, np.asarray(times), max_frames)
    rounded = np.round(pooled, 2)
    return SpectrogramResponse(
        recording_id=recording_id,
        kind=kind,
        dsp_version=version,
        n_bins=int(rounded.shape[0]),
        n_frames=int(rounded.shape[1]),
        frames_pooled=factor,
        duration_s=float(summary["duration_s"]),
        freqs_hz=_f(freqs),
        times_s=_f(t),
        min_db=float(rounded.min()),
        max_db=float(rounded.max()),
        values=rounded.tolist(),
    )


@router.post("/recordings/{recording_id}/retry", status_code=202)
def retry_processing(
    recording_id: str = Depends(valid_recording_id),
    services: Services = Depends(get_services),
) -> dict[str, str]:
    rec = _get_or_404(services, recording_id)
    with services.db.transaction() as conn:
        if JobRepo.has_active(conn, rec.id, DSP_STAGE):
            raise NotReady("a processing job is already queued or running")
        JobRepo.enqueue(conn, rec.id, DSP_STAGE)
        RecordingRepo.set_status(conn, rec.id, "uploaded", None)
    return {"recording_id": rec.id, "status": "uploaded"}


@router.delete("/recordings/{recording_id}", status_code=204)
def delete_recording(
    recording_id: str = Depends(valid_recording_id),
    services: Services = Depends(get_services),
) -> Response:
    rec = _get_or_404(services, recording_id)
    # Privacy cascade: compositions made from this recording contain its audio, so they go too.
    services.compositions.delete_for_recording(rec.id)
    # Row first (cascades to assets/features/jobs), then files. A crash between the two
    # leaves orphan files that are harmless and cleaned by the next delete of the same id.
    with services.db.transaction() as conn:
        ann = AnnotationRepo.active(conn, rec.id)
        base = PredictionRepo.latest(conn, rec.id, "base")
        # cascades: assets, features, jobs, embeddings, predictions, annotations, exemplars
        RecordingRepo.delete(conn, rec.id)
        EventRepo.append(
            conn, RECORDING_DELETED, {"content_hash": rec.content_hash}, recording_id=rec.id
        )
        if ann or base:
            services.memory.on_recording_deleted(
                conn, rec.id, ann.label_ids if ann else [], base.model_version_id if base else None
            )
    services.blobs.delete_recording_dirs(rec.id)
    return Response(status_code=204)
