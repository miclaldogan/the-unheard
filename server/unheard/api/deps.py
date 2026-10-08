"""Application services container and FastAPI dependencies."""

from __future__ import annotations

import secrets
from dataclasses import dataclass

from fastapi import Depends, Request
from fastapi.security.utils import get_authorization_scheme_param

from unheard.config import Settings
from unheard.errors import NotFound, Unauthorized
from unheard.ingest.decode import Decoder
from unheard.ingest.service import IngestService
from unheard.jobs.worker import JobWorker
from unheard.storage.blobs import BlobStore
from unheard.storage.db import Database
from unheard.storage.ids import is_valid_id


@dataclass
class Services:
    settings: Settings
    db: Database
    blobs: BlobStore
    decoder: Decoder
    ingest: IngestService
    worker: JobWorker

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
        worker = JobWorker(
            db, blobs, poll_s=settings.worker_poll_s, max_attempts=settings.max_job_attempts
        )
        return cls(settings, db, blobs, decoder, ingest, worker)

    def close(self) -> None:
        self.worker.stop()
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
