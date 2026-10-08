"""Embedding (de)serialisation: float32 little-endian blobs, never pickle."""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray


def to_blob(vec: NDArray[np.floating]) -> bytes:
    v = np.asarray(vec, dtype="<f4").ravel()
    if not np.all(np.isfinite(v)):
        raise ValueError("embedding contains non-finite values")
    return v.tobytes()


def from_blob(blob: bytes, dim: int | None = None) -> NDArray[np.float32]:
    v = np.frombuffer(blob, dtype="<f4")
    if dim is not None and v.size != dim:
        raise ValueError(f"embedding blob has {v.size} values, expected {dim}")
    return v.astype(np.float32)


def l2_normalize(vec: NDArray[np.floating], eps: float = 1e-12) -> NDArray[np.float32]:
    v = np.asarray(vec, dtype=np.float32)
    n = float(np.linalg.norm(v))
    return (v / max(n, eps)).astype(np.float32)
