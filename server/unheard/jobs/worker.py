"""In-process job worker: one thread, polls the ``job`` table (doc 08 "Background jobs").

Stages: ``dsp`` (M1) and ``infer`` (M2, needs a ModelManager + MemoryService). After a
successful ``dsp`` stage an ``infer`` job is queued automatically when ``auto_infer`` is on.
Inference failures never change the recording's ``status``: features stay usable, the
failure is recorded on the job row and as an ``AudioInferenceFailed`` event.
"""

from __future__ import annotations

import logging
import threading
import traceback
from collections.abc import Callable
from typing import Any

from unheard.errors import AppError
from unheard.events import AUDIO_INFERENCE_FAILED, JOB_FAILED
from unheard.jobs.inference import run_infer_stage
from unheard.jobs.pipeline import run_dsp_stage
from unheard.memory.service import MemoryService
from unheard.models.manager import ModelManager
from unheard.storage.blobs import BlobStore
from unheard.storage.db import Database
from unheard.storage.repos import EventRepo, JobRepo, JobRow, RecordingRepo

log = logging.getLogger(__name__)

StageFn = Callable[[Database, BlobStore, str], object]


class JobWorker:
    def __init__(
        self,
        db: Database,
        blobs: BlobStore,
        *,
        poll_s: float = 0.25,
        max_attempts: int = 3,
        models: ModelManager | None = None,
        memory: MemoryService | None = None,
        auto_infer: bool = False,
    ) -> None:
        self.db = db
        self.blobs = blobs
        self.poll_s = poll_s
        self.max_attempts = max_attempts
        self.models = models
        self.memory = memory
        self.auto_infer = auto_infer
        self.visual: Any = None  # VisualService, set by Services.build
        self.stages: dict[str, StageFn] = {"dsp": run_dsp_stage}
        if models is not None and memory is not None:
            self.stages["infer"] = lambda db_, blobs_, rid: run_infer_stage(
                db_, blobs_, rid, manager=models, memory=memory
            )
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # -- lifecycle ------------------------------------------------------------
    def start(self) -> None:
        with self.db.connection() as conn:
            n = JobRepo.reset_running(conn)
        if n:
            log.warning("re-queued %d job(s) left running by a previous process", n)
        self._thread = threading.Thread(target=self._loop, name="unheard-worker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                if not self.run_one():
                    self._stop.wait(self.poll_s)
            except Exception:  # never let the worker die
                log.exception("worker loop error")
                self._stop.wait(self.poll_s)

    # -- execution ------------------------------------------------------------
    def run_pending(self) -> int:
        n = 0
        while self.run_one():
            n += 1
        return n

    def run_one(self) -> bool:
        with self.db.transaction() as conn:
            job = JobRepo.claim_next(conn)
            if job is None:
                return False
            if job.stage == "dsp":
                RecordingRepo.set_status(conn, job.recording_id, "processing")
        self._execute(job)
        return True

    def _execute(self, job: JobRow) -> None:
        fn = self.stages.get(job.stage)
        if fn is None:
            self._fail(job, f"unknown stage '{job.stage}'", retryable=False)
            return
        try:
            fn(self.db, self.blobs, job.recording_id)
        except Exception as e:
            retryable = isinstance(e, AppError) and e.retryable
            detail = f"{type(e).__name__}: {e}"
            log.error(
                "job %s (%s) failed: %s\n%s", job.id, job.stage, detail, traceback.format_exc()
            )
            self._fail(job, detail, retryable=retryable)
            return
        with self.db.transaction() as conn:
            JobRepo.finish(conn, job.id, "done")
            if job.stage == "dsp":
                RecordingRepo.set_status(conn, job.recording_id, "ready", None)
                if self.auto_infer and not JobRepo.has_active(conn, job.recording_id, "infer"):
                    JobRepo.enqueue(conn, job.recording_id, "infer")
        if self.visual is not None:
            try:
                self.visual.ensure_artifact(job.recording_id)
            except Exception:  # the specimen is derived data; never fail the job for it
                log.exception("artifact generation failed for %s", job.recording_id)

    def _fail(self, job: JobRow, detail: str, *, retryable: bool) -> None:
        with self.db.transaction() as conn:
            if retryable and job.attempts < self.max_attempts:
                JobRepo.finish(conn, job.id, "queued", detail)
                return
            JobRepo.finish(conn, job.id, "failed", detail)
            if job.stage == "dsp":
                RecordingRepo.set_status(
                    conn,
                    job.recording_id,
                    "failed",
                    {"stage": job.stage, "message": detail, "attempts": job.attempts},
                )
                EventRepo.append(
                    conn,
                    JOB_FAILED,
                    {"job_id": job.id, "stage": job.stage, "error": detail},
                    recording_id=job.recording_id,
                )
            else:
                EventRepo.append(
                    conn,
                    AUDIO_INFERENCE_FAILED,
                    {"job_id": job.id, "stage": job.stage, "error": detail},
                    recording_id=job.recording_id,
                )
