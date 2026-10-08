"""Fusion/novelty tests with deterministic fake embeddings (no model)."""

from __future__ import annotations

import numpy as np
import pytest

from unheard.memory.engine import FusionParams, MemoryIndex, fuse, prototype

rng = np.random.default_rng(0)
D = 16
LABELS = ["water", "wind", "birds", "engine"]


def unit(v: np.ndarray) -> np.ndarray:
    return (v / np.linalg.norm(v)).astype(np.float32)


# orthogonal-ish "text" anchors and a query that leans towards water in the ears
ANCHORS = {lab: unit(rng.standard_normal(D)) for lab in LABELS}


def cos_for(x: np.ndarray) -> np.ndarray:
    return np.array(
        [float(ANCHORS[lab] @ x) * 0.5 for lab in LABELS]
    )  # scaled into CLAP-like range


def index_from(pairs: list[tuple[np.ndarray, str]], rec_prefix: str = "r") -> MemoryIndex:
    if not pairs:
        return MemoryIndex.empty(D)
    return MemoryIndex(
        vecs=np.stack([p[0] for p in pairs]).astype(np.float32),
        label_ids=[p[1] for p in pairs],
        recording_ids=[f"{rec_prefix}{i}" for i in range(len(pairs))],
        exemplar_ids=[f"x{i}" for i in range(len(pairs))],
        weights=np.ones(len(pairs), np.float32),
    )


P = FusionParams()
QUERY = unit(ANCHORS["water"] + 0.6 * ANCHORS["wind"] + 0.1 * rng.standard_normal(D))


def test_no_memory_equals_base_ranking() -> None:
    res = fuse(QUERY, LABELS, cos_for(QUERY), index_from([]), P)
    base_order = [LABELS[i] for i in np.argsort(-cos_for(QUERY))]
    assert [c.label_id for c in res.candidates] == base_order
    assert all(c.lambda_ == 0 and c.memory_similarity is None for c in res.candidates)
    assert res.novelty["memory_size"] == 0 and res.novelty["nothing_similar_remembered"] is True
    assert abs(sum(c.fused_score for c in res.candidates) - 1) < 1e-9


def test_one_example_shifts_but_does_not_dominate() -> None:
    # one exemplar very similar to the query, labelled "wind" (the ears' second choice)
    ex = unit(QUERY + 0.05 * rng.standard_normal(D))
    res = fuse(QUERY, LABELS, cos_for(QUERY), index_from([(ex, "wind")]), P)
    wind = next(c for c in res.candidates if c.label_id == "wind")
    water = next(c for c in res.candidates if c.label_id == "water")
    assert wind.n_exemplars == 1 and wind.lambda_ == pytest.approx(1 / (1 + P.kappa))
    assert res.novelty["relevant_exemplars"] == 1.0
    assert wind.memory_similarity is not None and wind.memory_similarity > 0.9
    base = fuse(QUERY, LABELS, cos_for(QUERY), index_from([]), P)
    assert wind.fused_score > next(c for c in base.candidates if c.label_id == "wind").fused_score
    # λ = 0.25 for a single example: water (strong ears) still ranks first
    assert water.rank == 1


def test_multiple_consistent_examples_win() -> None:
    exs = [(unit(QUERY + 0.05 * rng.standard_normal(D)), "wind") for _ in range(5)]
    res = fuse(QUERY, LABELS, cos_for(QUERY), index_from(exs), P)
    assert res.candidates[0].label_id == "wind"
    assert res.candidates[0].evidence in ("memory", "both")
    assert res.novelty["nearest_exemplar_similarity"] > P.tau_memory_strong


def test_contradictory_examples_split_memory() -> None:
    exs = [
        (unit(QUERY + 0.05 * rng.standard_normal(D)), lab)
        for lab in ("wind", "birds", "wind", "birds")
    ]
    res = fuse(QUERY, LABELS, cos_for(QUERY), index_from(exs), P)
    wind = next(c for c in res.candidates if c.label_id == "wind")
    birds = next(c for c in res.candidates if c.label_id == "birds")
    assert wind.memory_score is not None and birds.memory_score is not None
    assert abs(wind.memory_score - birds.memory_score) < 0.25


def test_far_memory_does_not_vote_and_novelty_flags() -> None:
    # exemplars orthogonal to the query (cosine ≈ 0): remembered, but nothing like this sound
    def orth() -> np.ndarray:
        v = rng.standard_normal(D)
        return unit(v - (v @ QUERY) * QUERY)

    far = [(orth(), "engine") for _ in range(6)]
    res = fuse(QUERY, LABELS, cos_for(QUERY), index_from(far), P)
    engine = next(c for c in res.candidates if c.label_id == "engine")
    assert engine.rank != 1
    assert res.novelty["nearest_exemplar_similarity"] < P.tau_novel
    assert res.novelty["nothing_similar_remembered"] is True
    assert res.novelty["lambda"] == 0.0  # far memory carries no weight


def test_unknown_input_diffuse_ears_and_no_memory_is_novel() -> None:
    q = unit(rng.standard_normal(D))  # unrelated to every anchor
    cos = np.full(len(LABELS), 0.1) + 0.001 * rng.standard_normal(len(LABELS))
    res = fuse(q, LABELS, cos, index_from([]), P)
    assert res.novelty["novel"] is True
    assert res.novelty["base_entropy_normalised"] > P.tau_entropy
    assert res.novelty["fused_margin"] < P.tau_margin


def test_strong_ears_evidence_is_not_novel() -> None:
    cos = np.array([0.6, 0.1, 0.1, 0.1])
    res = fuse(QUERY, LABELS, cos, index_from([]), P)
    assert res.novelty["novel"] is False and res.candidates[0].label_id == "water"


def test_disagreement_detected() -> None:
    cos = np.array([0.6, 0.1, 0.1, 0.1])  # ears: water
    exs = [
        (unit(QUERY + 0.05 * rng.standard_normal(D)), "engine") for _ in range(4)
    ]  # memory: engine
    res = fuse(QUERY, LABELS, cos, index_from(exs), P)
    assert res.novelty["disagreement"] is True
    assert res.novelty["ears_top"] == "water" and res.novelty["memory_top"] == "engine"


def test_prototype_math() -> None:
    v = np.stack([unit(ANCHORS["water"] + 0.1 * rng.standard_normal(D)) for _ in range(4)])
    p, n_eff, sigma = prototype(v)
    assert np.linalg.norm(p) == pytest.approx(1.0, abs=1e-6)
    assert n_eff == pytest.approx(4.0) and 0 <= sigma < 0.1
    with pytest.raises(ValueError):
        prototype(np.zeros((0, D)))


def test_fusion_is_deterministic() -> None:
    exs = [(unit(QUERY + 0.05 * rng.standard_normal(D)), "wind") for _ in range(3)]
    idx = index_from(exs)
    a = fuse(QUERY, LABELS, cos_for(QUERY), idx, P)
    b = fuse(QUERY, LABELS, cos_for(QUERY), idx, P)
    assert [(c.label_id, c.fused_score) for c in a.candidates] == [
        (c.label_id, c.fused_score) for c in b.candidates
    ]
