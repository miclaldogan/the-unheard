"""LAION-CLAP adapter (``laion/clap-htsat-unfused`` via ``transformers``).

Preprocessing contract (``PREPROCESSING_VERSION = 1``):
* input: canonical mono float PCM at 48 kHz (CLAP's native rate; no resampling needed)
* windows: 10 s, hop 5 s; a recording ≤ 10 s is a single window; a final partial window is
  kept if it is ≥ 2 s long (the processor repeat-pads it to 10 s)
* per-window audio embedding from ``get_audio_features`` (projection head), L2-normalised
* recording embedding = L2-normalised mean of window embeddings
* label score per window = cosine(audio, text); recording-level = **max over windows**
  (presence semantics: a sound present in any window counts)

Scores are cosine similarities in roughly [0, 0.6] for this model; they are not
probabilities. Determinism: no random truncation is triggered because windows never exceed
10 s; torch runs in inference mode with a fixed thread count.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

from unheard.models.contracts import (
    AudioInferenceInput,
    Embedding,
    InferenceResult,
    LabelScore,
    ModelError,
    ModelInfo,
)
from unheard.storage.vectors import l2_normalize

log = logging.getLogger(__name__)

PREPROCESSING_VERSION = 1
WINDOW_S = 10.0
HOP_S = 5.0
MIN_TAIL_S = 2.0
DEFAULT_MODEL = "laion/clap-htsat-unfused"
LICENSE_NOTE = (
    "LAION-CLAP code: Apache-2.0 (LAION-AI/CLAP). Weights 'laion/clap-htsat-unfused' on the "
    "Hugging Face Hub, model card lists Apache-2.0; trained on LAION-Audio-630K and AudioSet "
    "(dataset licences vary). Verify before redistribution; this project downloads the weights, "
    "it never ships them."
)


@dataclass
class WindowEmbedding:
    idx: int
    start_s: float
    end_s: float
    vec: NDArray[np.float32]


def plan_windows(
    duration_s: float, window_s: float = WINDOW_S, hop_s: float = HOP_S
) -> list[tuple[float, float]]:
    if duration_s <= window_s:
        return [(0.0, duration_s)]
    out: list[tuple[float, float]] = []
    start = 0.0
    while start + window_s <= duration_s + 1e-9:
        out.append((start, start + window_s))
        start += hop_s
    tail = duration_s - start
    if tail >= MIN_TAIL_S and (not out or out[-1][1] < duration_s - 1e-6):
        out.append((start, duration_s))
    return out


class ClapAudioModel:
    """Implements ``AudioModel`` plus text embedding for open-vocabulary labels."""

    def __init__(
        self,
        name: str = DEFAULT_MODEL,
        *,
        device: str = "cpu",
        allow_download: bool = False,
        threads: int | None = None,
    ) -> None:
        self.name = name
        self.device = device
        self.allow_download = allow_download
        self.threads = threads
        self._model: Any = None
        self._processor: Any = None
        self.revision = "unknown"
        self.embedding_dim = 0
        self.load_seconds: float | None = None
        self._labels: list[tuple[str, NDArray[np.float32]]] = []

    # -- lifecycle -----------------------------------------------------------
    def load(self) -> None:
        if not self.allow_download:
            os.environ.setdefault("HF_HUB_OFFLINE", "1")
            os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
        t0 = time.perf_counter()
        import torch
        from transformers import ClapModel, ClapProcessor

        if self.threads:
            torch.set_num_threads(self.threads)
        model = ClapModel.from_pretrained(self.name)
        processor = ClapProcessor.from_pretrained(self.name)
        model.eval()
        if self.device != "cpu":
            model.to(self.device)
        self._model = model
        self._processor = processor
        self.embedding_dim = int(model.config.projection_dim)
        self.revision = _resolve_revision(self.name, model)
        self.load_seconds = time.perf_counter() - t0
        log.info(
            "loaded %s@%s on %s in %.1fs (dim %d)",
            self.name,
            self.revision,
            self.device,
            self.load_seconds,
            self.embedding_dim,
        )

    def unload(self) -> None:
        self._model = None
        self._processor = None
        self._labels = []

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def info(self) -> ModelInfo:
        return ModelInfo(
            model_id=self.name,
            model_version=self.revision,
            license_note=LICENSE_NOTE,
            input_sample_rate=48_000,
            embedding_dim=self.embedding_dim or None,
            label_space="open-vocabulary (zero-shot text prompts)",
        )

    # -- text ----------------------------------------------------------------
    def embed_text(self, prompts: list[str]) -> NDArray[np.float32]:
        import torch

        self._require()
        out = np.zeros((len(prompts), self.embedding_dim), dtype=np.float32)
        with torch.inference_mode():
            for i in range(0, len(prompts), 16):
                batch = prompts[i : i + 16]
                inputs = self._processor(text=batch, return_tensors="pt", padding=True)
                inputs = {k: v.to(self.device) for k, v in inputs.items()}
                feats = self._model.get_text_features(**inputs).float().cpu().numpy()
                for j, f in enumerate(feats):
                    out[i + j] = l2_normalize(f)
        return out

    def set_label_space(self, labels: list[tuple[str, NDArray[np.float32]]]) -> None:
        self._labels = [(lid, np.asarray(v, dtype=np.float32)) for lid, v in labels]

    # -- audio ---------------------------------------------------------------
    def embed_windows(
        self, samples: NDArray[np.floating], sample_rate: int
    ) -> list[WindowEmbedding]:
        import torch

        self._require()
        if sample_rate != 48_000:
            from unheard.ingest.decode import resample_poly

            samples = resample_poly(np.asarray(samples, dtype=np.float64), sample_rate, 48_000)
            sample_rate = 48_000
        x = np.asarray(samples, dtype=np.float32)
        duration = x.size / sample_rate
        plan = plan_windows(duration)
        clips = [x[int(s * sample_rate) : int(e * sample_rate)] for s, e in plan]
        out: list[WindowEmbedding] = []
        with torch.inference_mode():
            for i in range(0, len(clips), 4):
                batch = clips[i : i + 4]
                inputs = self._processor(
                    audio=batch, sampling_rate=sample_rate, return_tensors="pt"
                )
                inputs = {k: v.to(self.device) for k, v in inputs.items()}
                feats = self._model.get_audio_features(**inputs).float().cpu().numpy()
                for j, f in enumerate(feats):
                    s, e = plan[i + j]
                    out.append(WindowEmbedding(i + j, float(s), float(e), l2_normalize(f)))
        return out

    def infer(self, inp: AudioInferenceInput) -> InferenceResult:
        t0 = time.perf_counter()
        try:
            windows = self.embed_windows(inp.samples, inp.sample_rate)
        except Exception as e:  # noqa: BLE001
            return InferenceResult(
                status="failed",
                model=self.info(),
                error=ModelError("INFERENCE_FAILED", _safe(str(e)), retryable=_retryable(e)),
            )
        pooled = l2_normalize(np.mean([w.vec for w in windows], axis=0))
        preds: list[LabelScore] = []
        if self._labels:
            mat = np.stack([v for _, v in self._labels])  # (L, d)
            per_window = np.stack([mat @ w.vec for w in windows])  # (W, L)
            rec_scores = per_window.max(axis=0)
            order = np.argsort(-rec_scores)
            preds = [LabelScore(self._labels[i][0], float(rec_scores[i])) for i in order]
        res = InferenceResult(
            status="ok",
            model=self.info(),
            predictions=preds,
            embedding=Embedding(vector=pooled, window_idx=None),
        )
        res_windows = windows  # attach for the pipeline
        self._last = {"windows": res_windows, "seconds": time.perf_counter() - t0}
        return res

    def infer_full(
        self, inp: AudioInferenceInput
    ) -> tuple[InferenceResult, list[WindowEmbedding], float]:
        res = self.infer(inp)
        last = getattr(self, "_last", {"windows": [], "seconds": 0.0})
        return res, list(last["windows"]), float(last["seconds"])

    def _require(self) -> None:
        if self._model is None:
            raise RuntimeError("model not loaded")


def _resolve_revision(name: str, model: Any) -> str:
    commit = getattr(getattr(model, "config", None), "_commit_hash", None)
    if commit:
        return str(commit)
    try:
        from huggingface_hub import constants

        snaps = Path(constants.HF_HUB_CACHE) / ("models--" + name.replace("/", "--")) / "snapshots"
        dirs = sorted(p.name for p in snaps.iterdir()) if snaps.is_dir() else []
        return dirs[-1] if dirs else "local"
    except Exception:  # noqa: BLE001
        return "local"


def _safe(msg: str) -> str:
    """Strip filesystem paths from error text before it reaches the API."""
    import re

    return re.sub(r"/[^\s'\"]+", "<path>", msg)[:300]


def _retryable(e: Exception) -> bool:
    name = type(e).__name__
    return "OutOfMemory" in name or "Timeout" in name
