"""Managed model lifecycle: one lazily-loaded instance, a lock, explicit status.

Status: ``disabled`` (UNHEARD_MODEL=none) · ``not_loaded`` · ``loading`` · ``ready`` · ``failed``.
The model is never loaded on import; the worker loads it on the first inference job (or
``POST /api/model/load``). Inference calls are serialised by ``lock``.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from unheard.models.clap import PREPROCESSING_VERSION, ClapAudioModel

log = logging.getLogger(__name__)


@dataclass
class ModelStatus:
    status: str
    model_id: str | None
    revision: str | None
    device: str
    embedding_dim: int | None
    preprocessing_version: int
    load_seconds: float | None
    error: str | None
    loaded_at: float | None = None
    extra: dict[str, Any] = field(default_factory=dict)


class ModelManager:
    def __init__(
        self, *, model_name: str | None, device: str, allow_download: bool, threads: int | None
    ) -> None:
        self.model_name = model_name
        self.device = device
        self.allow_download = allow_download
        self.threads = threads
        self.lock = threading.RLock()
        self._model: ClapAudioModel | None = None
        self._status = "disabled" if not model_name or model_name == "none" else "not_loaded"
        self._error: str | None = None
        self._loaded_at: float | None = None

    @property
    def enabled(self) -> bool:
        return self._status != "disabled"

    def status(self) -> ModelStatus:
        m = self._model
        return ModelStatus(
            status=self._status,
            model_id=self.model_name if self.enabled else None,
            revision=m.revision if m and m.loaded else None,
            device=self.device,
            embedding_dim=m.embedding_dim if m and m.loaded else None,
            preprocessing_version=PREPROCESSING_VERSION,
            load_seconds=m.load_seconds if m else None,
            error=self._error,
            loaded_at=self._loaded_at,
        )

    def get(self) -> ClapAudioModel:
        """Return the loaded model, loading it on first use. Raises on failure."""
        if not self.enabled:
            raise RuntimeError("audio model disabled (UNHEARD_MODEL=none)")
        with self.lock:
            if self._model is not None and self._model.loaded:
                return self._model
            self._status = "loading"
            self._error = None
            try:
                m = ClapAudioModel(
                    self.model_name or "",
                    device=self.device,
                    allow_download=self.allow_download,
                    threads=self.threads,
                )
                m.load()
            except Exception as e:  # noqa: BLE001
                self._status = "failed"
                self._error = f"{type(e).__name__}: {str(e)[:200]}"
                log.exception("model load failed")
                raise
            self._model = m
            self._status = "ready"
            self._loaded_at = time.time()
            return m

    def unload(self) -> None:
        with self.lock:
            if self._model:
                self._model.unload()
            self._model = None
            if self.enabled:
                self._status = "not_loaded"
