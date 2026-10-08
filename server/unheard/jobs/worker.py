"""In-process job worker: one thread, polls the ``job`` table (doc 08 "Background jobs").

Also exposes ``run_pending`` so tests can drive the queue synchronously.
"""

from __future__ import annotations

import logging
import threading
import traceback
from collections.abc import Callable

from unheard.errors import AppError
from unheard.events import JOB_FAILED
from unheard.jobs.pipeline import run_dsp_stage
from unheard.storage.blobs import BlobStore
from unheard.storage.db import Database
from unheard.storage.repos import EventRepo, JobRepo, JobRow, RecordingRepo

log = logging.getLogger(__name__)

StageFn = Callable[[Database, BlobStore, str], object]


class JobWorker:
    def __init__(
        self, db: Database, blobs: BlobStore, *, poll_s: float = 0.25, max_attempts: int = 3
    ) -> None:
        self.db = db
        self.blobs = blobs
        self.poll_s = poll_s
        self.max_attempts = max_attempts
        self.stages: dict[str, StageFn] = {"dsp": run_dsp_stage}
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
            RecordingRepo.set_status(conn, job.recording_id, "ready", None)

    def _fail(self, job: JobRow, detail: str, *, retryable: bool) -> None:
        with self.db.transaction() as conn:
            if retryable and job.attempts < self.max_attempts:
                JobRepo.finish(conn, job.id, "queued", detail)
                return
            JobRepo.finish(conn, job.id, "failed", detail)
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
