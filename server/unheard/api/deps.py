"""Application services container and FastAPI dependencies."""

from __future__ import annotations

import secrets
from dataclasses import dataclass

from fastapi import Depends, Request
from fastapi.security.utils import get_authorization_scheme_param

from unheard.atlas.service import AtlasService
from unheard.config import Settings
from unheard.errors import NotFound, Unauthorized
from unheard.ingest.decode import Decoder
from unheard.ingest.service import IngestService
from unheard.jobs.worker import JobWorker
from unheard.memory.service import MemoryService
from unheard.models.manager import ModelManager
from unheard.music.service import CompositionService
from unheard.narrative.service import NarrativeService
from unheard.storage.blobs import BlobStore
from unheard.storage.db import Database
from unheard.storage.ids import is_valid_id
from unheard.visual.service import VisualService


@dataclass
class Services:
    settings: Settings
    db: Database
    blobs: BlobStore
    decoder: Decoder
    ingest: IngestService
    worker: JobWorker
    models: ModelManager
    memory: MemoryService
    visual: VisualService
    atlas: AtlasService
    compositions: CompositionService
    narrative: NarrativeService

    @classmethod
    def build(cls, settings: Settings) -> Services:
        db = Database(settings.db_path)
        blobs = BlobStore(settings.data_dir)
        decoder = Decoder(
            ffmpeg_bin=settings.ffmpeg_bin,
            ffprobe_bin=settings.ffprobe_bin,
            timeout_s=settings.ffmpeg_timeout_s,
        )
        ingest = IngestService(settings, db, blobs, decoder)
        models = ModelManager(
            model_name=settings.model_name,
            device=settings.device,
            allow_download=settings.allow_model_download,
            threads=settings.torch_threads,
        )
        memory = MemoryService(settings, db)
        visual = VisualService(db, blobs, tau_strong=settings.fusion_tau_memory_strong)
        atlas = AtlasService(db, visual)
        memory.visual = visual
        worker = JobWorker(
            db,
            blobs,
            poll_s=settings.worker_poll_s,
            max_attempts=settings.max_job_attempts,
            models=models,
            memory=memory,
            auto_infer=settings.auto_infer and models.enabled,
        )
        worker.visual = visual
        compositions = CompositionService(db, blobs, poll_s=settings.worker_poll_s)
        narrative = NarrativeService(settings, db, blobs, models_enabled=lambda: models.enabled)
        return cls(
            settings,
            db,
            blobs,
            decoder,
            ingest,
            worker,
            models,
            memory,
            visual,
            atlas,
            compositions,
            narrative,
        )

    def close(self) -> None:
        self.narrative.stop()
        self.compositions.stop()
        self.worker.stop()
        self.models.unload()
        self.db.close()


def get_services(request: Request) -> Services:
    services: Services = request.app.state.services
    return services


def require_token(request: Request, services: Services = Depends(get_services)) -> None:
    token = services.settings.api_token
    if not token:
        return
    scheme, param = get_authorization_scheme_param(request.headers.get("Authorization"))
    if scheme.lower() != "bearer" or not secrets.compare_digest(param, token):
        raise Unauthorized("missing or invalid bearer token")


def valid_recording_id(recording_id: str) -> str:
    if not is_valid_id(recording_id):
        raise NotFound("recording not found")
    return recording_id
