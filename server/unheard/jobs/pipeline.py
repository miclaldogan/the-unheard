"""Processing stages run by the worker. M1: ``dsp`` only."""

from __future__ import annotations

import hashlib
import logging
import time

import numpy as np
import soundfile as sf

from unheard.dsp import DSP_VERSION, extract_features
from unheard.errors import NotFound
from unheard.events import FEATURES_EXTRACTED
from unheard.storage.blobs import BlobStore
from unheard.storage.db import Database
from unheard.storage.repos import AudioAssetRepo, EventRepo, FeatureSetRepo, RecordingRepo

log = logging.getLogger(__name__)


def run_dsp_stage(db: Database, blobs: BlobStore, recording_id: str) -> dict[str, float]:
    """Load canonical PCM, extract features, persist .npz + summary. Idempotent per version."""
    with db.connection() as conn:
        rec = RecordingRepo.get(conn, recording_id)
        asset = AudioAssetRepo.get(conn, recording_id, "canonical")
    if rec is None or asset is None:
        raise NotFound(f"recording {recording_id} has no canonical audio")

    t0 = time.perf_counter()
    samples, sr = sf.read(blobs.absolute(asset.path), dtype="float64", always_2d=False)
    samples = np.asarray(samples, dtype=np.float64)
    if samples.ndim != 1:
        samples = samples.mean(axis=1)
    t_load = time.perf_counter() - t0

    t1 = time.perf_counter()
    result = extract_features(samples, int(sr))
    t_dsp = time.perf_counter() - t1

    npz = result.to_npz_bytes()
    sha = hashlib.sha256(npz).hexdigest()
    rel = blobs.relative_path("artifacts", recording_id, f"features_v{DSP_VERSION}.npz")
    blobs.write_atomic(rel, npz)

    with db.transaction() as conn:
        FeatureSetRepo.upsert(
            conn,
            recording_id=recording_id,
            dsp_version=DSP_VERSION,
            summary=result.summary,
            artifact_path=rel,
            artifact_sha256=sha,
        )
        EventRepo.append(
            conn,
            FEATURES_EXTRACTED,
            {
                "dsp_version": DSP_VERSION,
                "summary_sha256": result.summary_hash(),
                "artifact_sha256": sha,
            },
            recording_id=recording_id,
        )
    timings = {"load_s": t_load, "dsp_s": t_dsp}
    log.info("dsp v%d done for %s (%.3f s)", DSP_VERSION, recording_id, t_dsp)
    return timings
