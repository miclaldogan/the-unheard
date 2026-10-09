"""Stable 2-D layout: PCA with a frozen basis + bounded repulsion (doc 05 §4).

* < 3 nodes: deterministic polar placement (seeded by recording id order).
* 3 … FREEZE_AT−1 nodes: basis refit on every update (set is tiny, movement acceptable).
* ≥ FREEZE_AT nodes: basis fitted once and persisted; later nodes are *projected* with the
  frozen basis and nudged by ≤ MAX_NUDGE against overlaps; existing nodes never move.
* ``rebuild`` refits the basis explicitly (user action) and re-projects everything.

Coordinates are in an abstract unit square-ish space ([-1, 1] nominal); the browser scales.
The 2-D projection of a 512-d space loses information by construction: ``explained_variance``
is reported so the UI can say how much of the spread the picture keeps.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

FREEZE_AT = 8
MAX_NUDGE = 0.08
MIN_DIST = 0.12
LAYOUT_VERSION = 1


@dataclass
class Basis:
    components: NDArray[np.float32]  # (2, dim)
    mean: NDArray[np.float32]  # (dim,)
    scale: float  # projection scale so that fitted points fall in ~[-1, 1]
    explained_variance: float
    n: int

    def to_array(self) -> NDArray[np.float32]:
        meta = np.zeros(self.mean.shape[0], dtype=np.float32)
        meta[0] = self.scale
        meta[1] = self.explained_variance
        meta[2] = float(self.n)
        return np.vstack([self.components, self.mean[None, :], meta[None, :]]).astype(np.float32)

    @classmethod
    def from_array(cls, arr: NDArray[np.float32]) -> Basis:
        comps, mean, meta = arr[:2], arr[2], arr[3]
        return cls(
            comps.astype(np.float32),
            mean.astype(np.float32),
            float(meta[0]),
            float(meta[1]),
            int(meta[2]),
        )


def fit_basis(vecs: NDArray[np.floating]) -> Basis:
    v = np.asarray(vecs, dtype=np.float64)
    mean = v.mean(axis=0)
    x = v - mean
    # deterministic SVD; sign convention: make the largest-|coefficient| entry positive
    _u, s, vt = np.linalg.svd(x, full_matrices=False)
    comps = vt[:2].copy()
    if comps.shape[0] < 2:
        comps = np.vstack([comps, np.zeros((2 - comps.shape[0], v.shape[1]))])
    for i in range(2):
        j = int(np.argmax(np.abs(comps[i])))
        if comps[i, j] < 0:
            comps[i] *= -1
    total = float((s**2).sum()) if s.size else 0.0
    ev = float((s[:2] ** 2).sum() / total) if total > 0 else 0.0
    proj = x @ comps.T
    extent = float(np.abs(proj).max()) if proj.size else 1.0
    scale = 0.85 / max(extent, 1e-6)
    return Basis(comps.astype(np.float32), mean.astype(np.float32), scale, ev, v.shape[0])


def project(basis: Basis, vec: NDArray[np.floating]) -> tuple[float, float]:
    p = (np.asarray(vec, dtype=np.float64) - basis.mean) @ basis.components.T * basis.scale
    return float(np.clip(p[0], -1.2, 1.2)), float(np.clip(p[1], -1.2, 1.2))


def polar_seed_positions(ids: list[str]) -> dict[str, list[float]]:
    out: dict[str, list[float]] = {}
    n = len(ids)
    for i, rid in enumerate(sorted(ids)):
        if n == 1:
            out[rid] = [0.0, 0.0]
        else:
            a = 2 * math.pi * i / n
            out[rid] = [round(0.5 * math.cos(a), 4), round(0.5 * math.sin(a), 4)]
    return out


def nudge(pos: tuple[float, float], others: list[tuple[float, float]]) -> tuple[float, float]:
    """Push a new point away from overlapping pinned points, by at most MAX_NUDGE."""
    x, y = pos
    dx = dy = 0.0
    for ox, oy in others:
        d = math.hypot(x - ox, y - oy)
        if d < MIN_DIST:
            if d < 1e-6:
                ang = (hash((round(x, 3), round(y, 3), len(others))) % 360) * math.pi / 180
                dx += math.cos(ang) * MIN_DIST
                dy += math.sin(ang) * MIN_DIST
            else:
                f = (MIN_DIST - d) / d
                dx += (x - ox) * f
                dy += (y - oy) * f
    m = math.hypot(dx, dy)
    if m > MAX_NUDGE:
        dx, dy = dx / m * MAX_NUDGE, dy / m * MAX_NUDGE
    return x + dx, y + dy
