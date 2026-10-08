"""``infer`` job stage: canonical audio → CLAP embeddings → base + fused predictions."""

from __future__ import annotations

import logging
import time
from typing import Any

import numpy as np
import soundfile as sf

from unheard.errors import AppError, NotFound
from unheard.events import AUDIO_INFERENCE_COMPLETED
from unheard.memory.service import BASE_SCORE_KIND, MemoryService
from unheard.models.clap import PREPROCESSING_VERSION
from unheard.models.contracts import AudioInferenceInput
from unheard.models.manager import ModelManager
from unheard.storage.blobs import BlobStore
from unheard.storage.db import Database
from unheard.storage.repos import AudioAssetRepo, EventRepo, RecordingRepo
from unheard.storage.repos_m2 import EmbeddingRepo, LabelRepo, ModelVersionRepo, PredictionRepo

log = logging.getLogger(__name__)


class ModelUnavailable(AppError):
    status = 503
    code = "MODEL_UNAVAILABLE"
    retryable = True


class InferenceFailed(AppError):
    status = 500
    code = "INFERENCE_FAILED"


def register_model_version(db: Database, manager: ModelManager, memory: MemoryService) -> str:
    """Make sure model_version row + vocabulary text embeddings exist. Returns model_version_id."""
    model = manager.get()
    info = model.info()
    with db.transaction() as conn:
        mv = ModelVersionRepo.get_or_create(
            conn,
            name=info.model_id,
            revision=info.model_version,
            framework="transformers+torch",
            preprocessing_version=PREPROCESSING_VERSION,
            embedding_dim=model.embedding_dim,
            input_sample_rate=48_000,
            license_note=info.license_note,
        )
        memory.ensure_vocabulary(conn)
        missing = memory.labels_needing_text_vec(conn, mv.id)
    if missing:
        vecs = model.embed_text([lab.text_prompt or f"The sound of {lab.name}." for lab in missing])
        with db.transaction() as conn:
            for lab, v in zip(missing, vecs, strict=True):
                LabelRepo.set_text_vec(conn, lab.id, v, mv.id)
    return mv.id


def run_infer_stage(
    db: Database,
    blobs: BlobStore,
    recording_id: str,
    *,
    manager: ModelManager,
    memory: MemoryService,
) -> dict[str, Any]:
    if not manager.enabled:
        raise ModelUnavailable("audio model is disabled")
    with db.connection() as conn:
        rec = RecordingRepo.get(conn, recording_id)
        asset = AudioAssetRepo.get(conn, recording_id, "canonical")
    if rec is None or asset is None:
        raise NotFound("recording has no canonical audio")
    try:
        model = manager.get()
    except Exception as e:  # noqa: BLE001
        raise ModelUnavailable(f"model load failed: {type(e).__name__}") from e
    model_version_id = register_model_version(db, manager, memory)

    with db.connection() as conn:
        label_ids, mat = memory.label_space(conn, model_version_id)
        names = memory.label_names(conn)
    samples, sr = sf.read(blobs.absolute(asset.path), dtype="float32", always_2d=False)
    samples = np.asarray(samples, dtype=np.float32)
    if samples.ndim != 1:
        samples = samples.mean(axis=1)

    with manager.lock:
        model.set_label_space(list(zip(label_ids, mat, strict=True)))
        t0 = time.perf_counter()
        res, windows, _ = model.infer_full(
            AudioInferenceInput(recording_id, samples, int(sr), samples.size / sr)
        )
        ms = (time.perf_counter() - t0) * 1000.0
    if res.status != "ok" or res.embedding is None:
        msg = res.error.message if res.error else "inference failed"
        raise InferenceFailed(msg)

    # per-window top labels for future temporal views
    win_json = []
    if label_ids:
        for w in windows:
            sims = mat @ w.vec
            order = np.argsort(-sims)[:3]
            win_json.append(
                {
                    "idx": w.idx,
                    "start_s": w.start_s,
                    "end_s": w.end_s,
                    "top": [
                        {
                            "label_id": label_ids[i],
                            "name": names[label_ids[i]][1],
                            "similarity": round(float(sims[i]), 6),
                        }
                        for i in order
                    ],
                }
            )
    results = [
        {
            "label_id": p.label,
            "slug": names[p.label][0],
            "name": names[p.label][1],
            "rank": r,
            "similarity": round(p.score, 6),
        }
        for r, p in enumerate(res.predictions, start=1)
    ]

    with db.transaction() as conn:
        for w in windows:
            EmbeddingRepo.upsert(
                conn,
                recording_id=recording_id,
                model_version_id=model_version_id,
                window_idx=w.idx,
                start_s=w.start_s,
                end_s=w.end_s,
                vec=w.vec,
            )
        EmbeddingRepo.upsert(
            conn,
            recording_id=recording_id,
            model_version_id=model_version_id,
            window_idx=-1,
            start_s=0.0,
            end_s=rec.duration_s,
            vec=res.embedding.vector,
        )
        PredictionRepo.delete_kind(conn, recording_id, "base")
        pid = PredictionRepo.insert(
            conn,
            recording_id=recording_id,
            model_version_id=model_version_id,
            kind="base",
            memory_version=0,
            score_kind=BASE_SCORE_KIND,
            results=results,
            windows=win_json,
            novelty=None,
            inference_ms=ms,
        )
        fused = memory.fuse_recording(conn, recording_id, model_version_id)
        fused_id = (
            memory.store_fused(conn, recording_id, model_version_id, fused, names)
            if fused and fused.candidates
            else None
        )
        EventRepo.append(
            conn,
            AUDIO_INFERENCE_COMPLETED,
            {
                "model_version_id": model_version_id,
                "prediction_id": pid,
                "fused_prediction_id": fused_id,
                "windows": len(windows),
                "inference_ms": round(ms, 1),
                "top": results[:3],
                "novel": bool(fused.novelty.get("novel")) if fused else None,
            },
            recording_id=recording_id,
        )
        if fused and fused.novelty.get("novel"):
            EventRepo.append(
                conn,
                "UnknownSoundObserved",
                {
                    "by": "system",
                    "novelty": {k: v for k, v in fused.novelty.items() if k != "neighbours"},
                },
                recording_id=recording_id,
            )
    log.info(
        "infer done for %s: %d windows, %.0f ms, top=%s",
        recording_id,
        len(windows),
        ms,
        results[0]["slug"] if results else None,
    )
    return {"inference_ms": ms, "windows": len(windows)}
