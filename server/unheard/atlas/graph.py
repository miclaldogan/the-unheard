"""Sparse similarity graph over pooled CLAP embeddings (one model version only).

Edge types (kept explicit, never merged):
* ``acoustic``     — mutual/one-way kNN by cosine (k = K_NEAREST) with cosine ≥ TAU_EDGE
* ``shared_label`` — both recordings carry the same active confirmed source label; each node
                     links only to its most similar same-label neighbours (≤ K_LABEL) so a
                     label never becomes a clique
Self-edges are excluded; edges are undirected and deduplicated (a < b).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

K_NEAREST = 3
TAU_EDGE = 0.45
K_LABEL = 2


@dataclass(frozen=True)
class Edge:
    a: str
    b: str
    type: str  # acoustic | shared_label
    weight: float  # cosine similarity
    label_id: str | None = None


def cosine_matrix(vecs: NDArray[np.floating]) -> NDArray[np.float64]:
    v = np.asarray(vecs, dtype=np.float64)
    if v.ndim != 2 or v.shape[0] == 0:
        return np.zeros((0, 0))
    n = np.linalg.norm(v, axis=1, keepdims=True)
    v = v / np.maximum(n, 1e-12)
    s = np.asarray(v @ v.T, dtype=np.float64)
    np.fill_diagonal(s, -1.0)
    return s


def build_edges(
    ids: list[str],
    vecs: NDArray[np.floating],
    labels: dict[str, list[str]],
    *,
    k: int = K_NEAREST,
    tau: float = TAU_EDGE,
    k_label: int = K_LABEL,
) -> list[Edge]:
    n = len(ids)
    if n < 2:
        return []
    s = cosine_matrix(vecs)
    seen: set[tuple[str, str, str]] = set()
    out: list[Edge] = []

    def add(i: int, j: int, typ: str, lid: str | None = None) -> None:
        if i == j:
            return
        a, b = sorted((ids[i], ids[j]))
        key = (a, b, typ + (lid or ""))
        if key in seen:
            return
        seen.add(key)
        out.append(Edge(a, b, typ, round(float(s[i, j]), 4), lid))

    for i in range(n):
        order = np.argsort(-s[i])[:k]
        for j in order:
            if s[i, j] >= tau:
                add(i, int(j), "acoustic")
    # shared labels
    by_label: dict[str, list[int]] = {}
    for idx, rid in enumerate(ids):
        for lid in labels.get(rid, []):
            by_label.setdefault(lid, []).append(idx)
    for lid, members in by_label.items():
        if len(members) < 2:
            continue
        for i in members:
            others = [j for j in members if j != i]
            others.sort(key=lambda j: -s[i, j])
            for j in others[:k_label]:
                add(i, j, "shared_label", lid)
    return out
