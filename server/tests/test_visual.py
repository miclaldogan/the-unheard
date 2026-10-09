"""Deterministic visual generation and graph/layout tests (no model, no HTTP)."""

from __future__ import annotations

import math

import numpy as np

from tests.fixtures import synth
from unheard.atlas.graph import build_edges
from unheard.atlas.layout import FREEZE_AT, Basis, fit_basis, nudge, polar_seed_positions, project
from unheard.dsp import extract_features
from unheard.visual.signature import (
    GENERATOR_VERSION,
    build_params,
    geometry_params,
    seed_from_hash,
    semantic_params,
)

SR = 48_000
SEM = semantic_params(
    label_name="Water",
    label_hue=200,
    state="hypothesis",
    resolution=0.5,
    confirmed_labels=[],
    descriptors=[],
    environment=None,
    mood=None,
    novelty=None,
)


def params_for(x: np.ndarray, content_hash: str = "abc") -> tuple[dict, int, str]:
    f = extract_features(x, SR)
    arrays = {k: f.arrays[k] for k in ("rms_envelope_db", "log_mel_db", "centroid_hz", "flux")}
    return build_params(
        content_hash=content_hash, summary=f.summary, arrays=arrays, semantic=SEM, dsp_version=1
    )


def bounded(geom: dict) -> None:
    for key in ("ring", "bands", "brightness_curve", "ticks"):
        assert all(0.0 <= v <= 1.0 and math.isfinite(v) for v in geom[key]), key
    for key in ("sharpness", "jitter", "fragmentation", "energy"):
        assert 0.0 <= geom[key] <= 1.0
    assert 0.6 <= geom["scale"] <= 1.0
    assert 2 <= geom["symmetry_order"] <= 8
    assert (
        len(geom["ring"]) == 128
        and len(geom["bands"]) == 32
        and len(geom["brightness_curve"]) == 32
    )


def test_same_input_same_params_and_seed() -> None:
    x = synth.environmental_like(SR, 4.0)
    a, seed_a, ha = params_for(x)
    b, seed_b, hb = params_for(x)
    assert a == b and seed_a == seed_b and ha == hb
    assert seed_from_hash("abc") == seed_a and seed_from_hash("abc", 2) != seed_a
    assert a["generator_version"] == GENERATOR_VERSION


def test_different_inputs_differ_meaningfully() -> None:
    tone, _, h1 = params_for(synth.sine(440, SR, 4.0))
    noise, _, h2 = params_for(synth.white_noise(SR, 4.0, seed=3))
    clicks, _, h3 = params_for(synth.click_train(4.0, SR, 4.0))
    assert len({h1, h2, h3}) == 3
    gt, gn, gc = tone["geometry"], noise["geometry"], clicks["geometry"]
    assert gn["sharpness"] > gt["sharpness"]  # noise is brighter than a 440 Hz tone
    assert gt["symmetry_order"] > gn["symmetry_order"]  # tonal → more fold symmetry
    assert gn["jitter"] > gt["jitter"]  # flatness drives irregularity
    assert len(gc["ticks"]) >= 12 and len(gt["ticks"]) <= 2  # onsets become ticks
    bounded(gt), bounded(gn), bounded(gc)


def test_label_changes_only_semantic_layer() -> None:
    x = synth.environmental_like(SR, 4.0)
    f = extract_features(x, SR)
    arrays = {k: f.arrays[k] for k in ("rms_envelope_db", "log_mel_db", "centroid_hz", "flux")}
    other = semantic_params(
        label_name="Wind",
        label_hue=30,
        state="confirmed",
        resolution=1.0,
        confirmed_labels=["Wind"],
        descriptors=["gusty"],
        environment="hill",
        mood="cold",
        novelty=None,
    )
    a, _, ha = build_params(
        content_hash="z", summary=f.summary, arrays=arrays, semantic=SEM, dsp_version=1
    )
    b, _, hb = build_params(
        content_hash="z", summary=f.summary, arrays=arrays, semantic=other, dsp_version=1
    )
    assert ha == hb and a["geometry"] == b["geometry"] and a["animation"] == b["animation"]
    assert a["semantic"] != b["semantic"] and b["semantic"]["hue"] == 30


def test_silence_and_clipping_are_safe() -> None:
    s, _, _ = params_for(synth.silence(SR, 4.0))
    bounded(s["geometry"])
    assert s["geometry"]["energy"] == 0.0 and all(v == 0.0 for v in s["geometry"]["ring"])
    c, _, _ = params_for(synth.clipped_sine(440, SR, 4.0))
    bounded(c["geometry"])
    assert c["geometry"]["energy"] > 0.9
    assert all(math.isfinite(v) for v in c["animation"]["envelope"])


def test_invalid_feature_values_are_normalised() -> None:
    summary = {
        "duration_s": float("nan"),
        "rms_dbfs": float("inf"),
        "spectral_centroid_hz": {"median": -5},
        "spectral_flatness": {"median": 7},
        "spectral_flux": {"median": float("nan"), "max": 0},
        "onset_times_s": [1.0, float("nan")],
    }
    arrays = {
        "rms_envelope_db": np.array([np.nan, -20.0]),
        "log_mel_db": np.full((64, 10), np.nan),
        "centroid_hz": np.array([np.inf]),
        "flux": np.array([np.nan]),
    }
    g = geometry_params(summary, arrays)
    bounded(g)


# ---------------------------------------------------------------------------- graph / layout


def unit(v: np.ndarray) -> np.ndarray:
    return v / np.linalg.norm(v)


def test_edges_are_sparse_valid_and_typed() -> None:
    rng = np.random.default_rng(0)
    base = unit(rng.standard_normal(16))
    ids = [f"r{i}" for i in range(10)]
    vecs = np.stack(
        [unit(base + 0.15 * rng.standard_normal(16)) for _ in range(5)]
        + [unit(rng.standard_normal(16)) for _ in range(5)]
    )
    labels = {"r0": ["L"], "r1": ["L"], "r2": ["L"], "r7": ["L"]}
    edges = build_edges(ids, vecs, labels)
    assert edges
    for e in edges:
        assert e.a in ids and e.b in ids and e.a != e.b and e.a < e.b
        assert e.type in ("acoustic", "shared_label")
        assert -1 <= e.weight <= 1
    acoustic = [e for e in edges if e.type == "acoustic"]
    assert len(acoustic) <= 10 * 3
    label_edges = [e for e in edges if e.type == "shared_label"]
    assert label_edges and all(e.label_id == "L" for e in label_edges)
    assert len(label_edges) < 6  # 4 members, k_label=2 → no clique (6 would be complete)
    # similarity correctness: a cluster member's acoustic edges go to cluster members
    for e in acoustic:
        if e.a == "r0":
            assert e.b in {"r1", "r2", "r3", "r4"}
    assert build_edges(["only"], vecs[:1], {}) == []


def test_layout_small_sets_and_stability() -> None:
    assert polar_seed_positions(["a"]) == {"a": [0.0, 0.0]}
    two = polar_seed_positions(["b", "a"])
    assert set(two) == {"a", "b"} and two["a"] != two["b"]
    rng = np.random.default_rng(1)
    vecs = np.stack([unit(rng.standard_normal(32)) for _ in range(FREEZE_AT)])
    basis = fit_basis(vecs)
    again = fit_basis(vecs)
    np.testing.assert_allclose(basis.components, again.components)
    assert 0 < basis.explained_variance <= 1
    pts = [project(basis, v) for v in vecs]
    assert all(-1.2 <= x <= 1.2 and -1.2 <= y <= 1.2 for x, y in pts)
    rt = Basis.from_array(basis.to_array())
    assert rt.n == FREEZE_AT and abs(rt.scale - basis.scale) < 1e-6
    # new point projected with the frozen basis does not move the others; nudge is bounded
    new = unit(rng.standard_normal(32))
    p = project(basis, new)
    q = nudge(p, pts)
    assert math.hypot(q[0] - p[0], q[1] - p[1]) <= 0.08 + 1e-9
    assert nudge(p, []) == p
