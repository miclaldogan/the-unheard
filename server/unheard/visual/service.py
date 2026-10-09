"""Visual service: builds/updates one artifact per recording from scientific tables."""

from __future__ import annotations

import logging
import sqlite3
from typing import Any

import numpy as np

from unheard.events import ARTIFACT_RENDERED
from unheard.storage.blobs import BlobStore
from unheard.storage.db import Database
from unheard.storage.repos import EventRepo, FeatureSetRepo, RecordingRepo
from unheard.storage.repos_m2 import AnnotationRepo, LabelRepo, PredictionRepo
from unheard.storage.repos_m3 import ArtifactRepo, ArtifactRow
from unheard.visual.signature import GENERATOR_VERSION, build_params, semantic_params

log = logging.getLogger(__name__)

ARRAY_KEYS = ("rms_envelope_db", "log_mel_db", "centroid_hz", "flux")


def semantic_state(
    conn: sqlite3.Connection, recording_id: str, tau_strong: float
) -> dict[str, Any]:
    """Derive the semantic layer from annotation + fused prediction (never from DSP)."""
    ann = AnnotationRepo.active(conn, recording_id)
    fused = PredictionRepo.latest(conn, recording_id, "fused")
    base = PredictionRepo.latest(conn, recording_id, "base")
    label_name = None
    hue = None
    confirmed: list[str] = []
    state = "hypothesis"
    resolution = 0.3
    novelty = fused.novelty if fused else None
    if ann and ann.is_unknown:
        state = "unknown"
        resolution = 0.0
    elif ann and ann.label_ids:
        lab = LabelRepo.get(conn, ann.label_ids[0])
        labs = [LabelRepo.get(conn, lid) for lid in ann.label_ids]
        confirmed = [x.name for x in labs if x is not None]
        if lab:
            label_name, hue = lab.name, lab.hue_seed
        state = "confirmed"
        resolution = 1.0
    elif fused and fused.results:
        top = fused.results[0]
        lab = LabelRepo.get(conn, top["label_id"])
        if lab:
            label_name, hue = lab.name, lab.hue_seed
        nov = fused.novelty or {}
        if nov.get("novel"):
            state, resolution = "unknown", 0.1
        else:
            margin = float(nov.get("fused_margin", 0.0) or 0.0)
            near = nov.get("nearest_exemplar_similarity")
            state = "uncertain" if margin < 0.3 else "hypothesis"
            resolution = (
                0.35
                + 0.4 * min(1.0, margin)
                + (0.25 if near is not None and near >= tau_strong else 0.0)
            )
    elif base is None:
        state, resolution = "uncertain", 0.2
    return semantic_params(
        label_name=label_name,
        label_hue=hue,
        state=state,
        resolution=resolution,
        confirmed_labels=confirmed,
        descriptors=ann.descriptors if ann else [],
        environment=ann.environment if ann else None,
        mood=ann.mood if ann else None,
        novelty=novelty,
    ) | {
        "model_version_id": base.model_version_id if base else None,
        "memory_version": fused.memory_version if fused else None,
    }


class VisualService:
    def __init__(self, db: Database, blobs: BlobStore, *, tau_strong: float = 0.75) -> None:
        self.db = db
        self.blobs = blobs
        self.tau_strong = tau_strong

    def _load_arrays(self, artifact_path: str) -> dict[str, Any]:
        path = self.blobs.absolute(artifact_path)
        if not path.is_file():
            return {}
        with np.load(path) as z:
            return {k: z[k] for k in ARRAY_KEYS if k in z.files}

    def ensure_artifact(self, recording_id: str, *, emit: bool = True) -> ArtifactRow | None:
        """Create or refresh the artifact (idempotent). Returns None when features are missing."""
        with self.db.connection() as conn:
            rec = RecordingRepo.get(conn, recording_id)
            fs = FeatureSetRepo.latest(conn, recording_id)
            if rec is None or fs is None:
                return None
            existing = ArtifactRepo.get(conn, recording_id, GENERATOR_VERSION)
            semantic = semantic_state(conn, recording_id, self.tau_strong)
        arrays = self._load_arrays(fs.artifact_path)
        params, seed, ghash = build_params(
            content_hash=rec.content_hash,
            summary=fs.summary,
            arrays=arrays,
            semantic=semantic,
            dsp_version=fs.dsp_version,
        )
        with self.db.transaction() as conn:
            row = ArtifactRepo.upsert(
                conn,
                recording_id=recording_id,
                generator_version=GENERATOR_VERSION,
                seed=seed,
                dsp_version=fs.dsp_version,
                model_version_id=semantic.get("model_version_id"),
                geometry_hash=ghash,
                params=params,
            )
            changed = (
                existing is None
                or existing.params.get("semantic") != params["semantic"]
                or existing.geometry_hash != ghash
            )
            if emit and changed:
                EventRepo.append(
                    conn,
                    ARTIFACT_RENDERED,
                    {
                        "artifact_id": row.id,
                        "generator_version": GENERATOR_VERSION,
                        "geometry_hash": ghash,
                        "state": semantic["state"],
                        "label": semantic["label"],
                        "new": existing is None,
                    },
                    recording_id=recording_id,
                )
        return row

    def get(self, recording_id: str) -> ArtifactRow | None:
        with self.db.connection() as conn:
            row = ArtifactRepo.get(conn, recording_id, GENERATOR_VERSION)
        if row is None or row.status == "stale":
            row = self.ensure_artifact(recording_id)
        return row

    def refresh_all(self) -> int:
        with self.db.connection() as conn:
            ids = [r.id for r in RecordingRepo.list(conn, limit=10000, offset=0)]
        n = 0
        for rid in ids:
            if self.ensure_artifact(rid, emit=False) is not None:
                n += 1
        return n
