"""Personal acoustic memory: kernel-kNN scores, log-linear fusion, novelty gate.

Pure NumPy, no I/O. Implements doc 04 §3–§4 with two practical additions:

* ``s_mem`` is Laplace-smoothed (``eps``) so a label that is absent from the k nearest
  exemplars gets a small but non-zero memory score instead of ``log 0``.
* Base scores are a softmax over cosine similarities with temperature ``t_base`` — a
  *relative ranking score over the current label space*, not a calibrated probability. The
  API reports the raw cosine alongside it so nothing is presented as a percentage.

Definitions (x = query embedding, e_i exemplar embeddings with labels y_i and weights w_i,
all L2-normalised so ``cos = dot``):

    s_base(c)  = softmax_c( cos(x, t_c) / t_base )                       (t_c = text embedding)
    kNN(x)     = k exemplars with highest cos(x, e_i)
    s_mem(c)   = (1−α)·Σ_{i∈kNN, y_i=c} w_i·exp(cos/T) / Σ_{i∈kNN} w_i·exp(cos/T) + α/L
    n_rel      = Σ_{i∈kNN} w_i·[cos(x,e_i) ≥ τ_n]          (relevant memory evidence)
    λ          = n_rel / (n_rel + κ)                         (0 when nothing similar is remembered)
    log f(c)   = (1−λ)·log s_base(c) + λ·log s_mem(c);       fused(c) = softmax_c(log f)

Deviation from doc 04 §3 (which uses a per-class λ_c = n_c/(n_c+κ)): a per-class λ leaves
labels with zero exemplars at their pure base score, so memory evidence *against* them can
never win — five consistent corrections "water → wind" would still rank water first. One
λ for the whole distribution, driven by how much near memory exists, fixes that while still
making a single example weak (λ = 1/(1+κ) = 0.25). The uniform floor α keeps log s_mem
finite for labels absent from the neighbourhood.

Novelty:  novel ⇔ [max_i cos(x,e_i) < τ_n  or no exemplars]
                  ∧ ([fused top1−top2 < τ_m] ∨ [H(s_base)/log L > τ_e])
Doc 04 §4 ANDs all three conditions; on ESC-50 that never fired (eval/reports). The nearest
exemplar cosine carries almost all the signal (AUROC 0.95), so the ears-side conditions are
ORed and loosened. All τ are empirical (docs/M2-REPORT.md "thresholds") — not guarantees.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
from numpy.typing import NDArray


@dataclass(frozen=True)
class FusionParams:
    k: int = 7
    t_mem: float = 0.07
    kappa: float = 3.0
    t_base: float = 0.05
    alpha: float = 0.10  # uniform floor mixed into the memory distribution
    tau_novel: float = 0.55  # max cosine to any exemplar below this → "nothing similar remembered"
    tau_margin: float = 0.60  # fused top1-top2 below this → ambiguous
    tau_entropy: float = 0.25  # normalised base entropy above this → diffuse first impression
    tau_memory_strong: float = 0.75  # nearest exemplar cosine at/above this → "I remember"
    tau_disagree: float = 0.5  # both base and memory argmax scores ≥ this and differ → disagreement


@dataclass
class MemoryIndex:
    """Active exemplars for one model version (rows aligned)."""

    vecs: NDArray[np.float32]  # (n, d)
    label_ids: list[str]
    recording_ids: list[str]
    exemplar_ids: list[str]
    weights: NDArray[np.float32]

    @classmethod
    def empty(cls, dim: int) -> MemoryIndex:
        return cls(np.zeros((0, dim), np.float32), [], [], [], np.zeros(0, np.float32))

    def __len__(self) -> int:
        return len(self.label_ids)

    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for lid in self.label_ids:
            out[lid] = out.get(lid, 0) + 1
        return out


@dataclass
class Candidate:
    label_id: str
    base_similarity: float  # cosine(audio, text prompt)
    base_score: float  # softmax over label space (relative)
    memory_similarity: float | None  # max cosine to an exemplar of this label, if any
    memory_score: float | None  # s_mem(c) if the label has exemplars in the kNN set, else None
    n_exemplars: int
    lambda_: float
    fused_score: float
    rank: int = 0
    evidence: str = "ears"  # ears | memory | both


@dataclass
class Neighbour:
    exemplar_id: str
    recording_id: str
    label_id: str
    similarity: float


@dataclass
class FusionResult:
    candidates: list[Candidate]
    neighbours: list[Neighbour]
    novelty: dict[str, Any]
    params: FusionParams = field(default_factory=FusionParams)

    def top(self, n: int = 5) -> list[Candidate]:
        return self.candidates[:n]


def softmax(x: NDArray[np.floating]) -> NDArray[np.float64]:
    z = np.asarray(x, dtype=np.float64)
    z = z - z.max()
    e = np.exp(z)
    return np.asarray(e / e.sum(), dtype=np.float64)


def normalised_entropy(p: NDArray[np.floating]) -> float:
    p = np.clip(np.asarray(p, dtype=np.float64), 1e-12, 1.0)
    h = float(-(p * np.log(p)).sum())
    return h / float(np.log(len(p))) if len(p) > 1 else 0.0


def base_scores(cosines: NDArray[np.floating], params: FusionParams) -> NDArray[np.float64]:
    return np.asarray(
        softmax(np.asarray(cosines, dtype=np.float64) / params.t_base), dtype=np.float64
    )


def knn(
    x: NDArray[np.floating], index: MemoryIndex, k: int
) -> tuple[NDArray[np.int64], NDArray[np.float64]]:
    if len(index) == 0:
        return np.zeros(0, np.int64), np.zeros(0, np.float64)
    sims = index.vecs @ np.asarray(x, dtype=np.float32)
    order = np.argsort(-sims)[:k]
    return order.astype(np.int64), sims[order].astype(np.float64)


def memory_scores(
    x: NDArray[np.floating], index: MemoryIndex, label_ids: list[str], params: FusionParams
) -> tuple[NDArray[np.float64], list[Neighbour], dict[str, float], float]:
    """Return (s_mem aligned with label_ids, neighbours, max-cos per label, n_rel)."""
    L = len(label_ids)
    idx, sims = knn(x, index, params.k)
    pos = {lid: i for i, lid in enumerate(label_ids)}
    num = np.zeros(L, dtype=np.float64)
    den = 0.0
    neighbours: list[Neighbour] = []
    for j, s in zip(idx.tolist(), sims.tolist(), strict=True):
        w = float(index.weights[j]) * float(np.exp(s / params.t_mem))
        den += w
        lid = index.label_ids[j]
        if lid in pos:
            num[pos[lid]] += w
        neighbours.append(Neighbour(index.exemplar_ids[j], index.recording_ids[j], lid, float(s)))
    if L and den > 0:
        s_mem = (1.0 - params.alpha) * (num / den) + params.alpha / L
    elif L:
        s_mem = np.full(L, 1.0 / L)
    else:
        s_mem = num
    n_rel = float(
        sum(
            float(index.weights[j])
            for j, s in zip(idx.tolist(), sims.tolist(), strict=True)
            if s >= params.tau_novel
        )
    )
    # max cosine per label over ALL exemplars (not only the k nearest) for display
    max_cos: dict[str, float] = {}
    if len(index):
        all_sims = index.vecs @ np.asarray(x, dtype=np.float32)
        for j, lid in enumerate(index.label_ids):
            v = float(all_sims[j])
            if v > max_cos.get(lid, -2.0):
                max_cos[lid] = v
    return s_mem, neighbours, max_cos, n_rel


def fuse(
    x: NDArray[np.floating],
    label_ids: list[str],
    cosines: NDArray[np.floating],
    index: MemoryIndex,
    params: FusionParams = FusionParams(),
) -> FusionResult:
    """Fuse base zero-shot cosines with personal memory for one query embedding."""
    L = len(label_ids)
    if L == 0:
        return FusionResult([], [], {"novel": True, "reason": "empty label space"}, params)
    s_base = base_scores(cosines, params)
    s_mem, neighbours, max_cos, n_rel = memory_scores(x, index, label_ids, params)
    counts = index.counts()
    n = np.array([counts.get(lid, 0) for lid in label_ids], dtype=np.float64)
    lam_global = n_rel / (n_rel + params.kappa)
    lam = np.full(L, lam_global)
    log_f = (1.0 - lam) * np.log(np.clip(s_base, 1e-12, None)) + lam * np.log(
        np.clip(s_mem, 1e-12, None)
    )
    fused = softmax(log_f)

    # which labels appear among the k nearest exemplars?
    in_knn = {nb.label_id for nb in neighbours}
    cands: list[Candidate] = []
    for i, lid in enumerate(label_ids):
        has_mem = lid in max_cos
        cands.append(
            Candidate(
                label_id=lid,
                base_similarity=float(cosines[i]),
                base_score=float(s_base[i]),
                memory_similarity=max_cos.get(lid),
                memory_score=float(s_mem[i]) if lid in in_knn else None,
                n_exemplars=int(n[i]),
                lambda_=float(lam[i]),
                fused_score=float(fused[i]),
                evidence="both" if has_mem else "ears",
            )
        )
    cands.sort(key=lambda c: -c.fused_score)
    for r, c in enumerate(cands, start=1):
        c.rank = r
        if (
            c.memory_similarity is not None
            and c.memory_similarity >= params.tau_memory_strong
            and c.lambda_ > 0
        ):
            c.evidence = "memory" if c.base_score < 0.5 else "both"

    top1 = cands[0].fused_score
    top2 = cands[1].fused_score if L > 1 else 0.0
    margin = top1 - top2
    entropy = normalised_entropy(s_base)
    nearest = max((nb.similarity for nb in neighbours), default=None)
    base_arg = label_ids[int(np.argmax(s_base))]
    mem_arg = label_ids[int(np.argmax(s_mem))] if len(index) else None
    disagreement = (
        mem_arg is not None
        and mem_arg != base_arg
        and float(s_base.max()) >= params.tau_disagree
        and float(s_mem.max()) >= params.tau_disagree
    )
    nothing_similar = nearest is None or nearest < params.tau_novel
    ears_undecided = margin < params.tau_margin or entropy > params.tau_entropy
    novel = bool(nothing_similar and ears_undecided)
    novelty = {
        "novel": novel,
        "nearest_exemplar_similarity": nearest,
        "fused_margin": float(margin),
        "base_entropy_normalised": float(entropy),
        "memory_size": len(index),
        "relevant_exemplars": float(n_rel),
        "lambda": float(lam_global),
        "nothing_similar_remembered": bool(nothing_similar),
        "disagreement": bool(disagreement),
        "ears_top": base_arg,
        "memory_top": mem_arg,
        "thresholds": {
            "tau_novel": params.tau_novel,
            "tau_margin": params.tau_margin,
            "tau_entropy": params.tau_entropy,
            "tau_memory_strong": params.tau_memory_strong,
        },
    }
    return FusionResult(cands, neighbours, novelty, params)


def prototype(
    vecs: NDArray[np.floating], weights: NDArray[np.floating] | None = None
) -> tuple[NDArray[np.float32], float, float]:
    """Weighted mean of L2-normalised vectors → (unit prototype, n_eff, sigma)."""
    v = np.asarray(vecs, dtype=np.float64)
    if v.ndim != 2 or v.shape[0] == 0:
        raise ValueError("need at least one vector")
    w = np.ones(v.shape[0]) if weights is None else np.asarray(weights, dtype=np.float64)
    mean = (w[:, None] * v).sum(axis=0) / w.sum()
    norm = float(np.linalg.norm(mean))
    proto = mean / max(norm, 1e-12)
    cos = v @ proto
    sigma = float(np.mean(1.0 - cos))
    n_eff = float(w.sum() ** 2 / (w**2).sum())
    return proto.astype(np.float32), n_eff, sigma
