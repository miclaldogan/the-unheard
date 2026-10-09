"""End-to-end pure pipeline: audio + feature arrays → analyses → roles → plan → render."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from numpy.typing import NDArray

from unheard.music.analysis import SourceAnalysis, analyze_source
from unheard.music.composer import MODES, compose_plan
from unheard.music.material import extract_material
from unheard.music.planner import canonical_plan_hash, plan_composition
from unheard.music.render import SR, render_plan
from unheard.music.roles import RoleDecision, assign_role


@dataclass
class SourceInput:
    key: str  # content hash
    samples: NDArray[np.float64]
    arrays: dict[str, NDArray[np.float64]]
    sample_rate: int = SR


@dataclass
class ComposeResult:
    plan: dict[str, Any]
    plan_hash: str
    analyses: dict[str, SourceAnalysis]
    roles: dict[str, RoleDecision]
    stems: dict[str, NDArray[np.float64]]
    master: NDArray[np.float64]
    metrics: dict[str, Any]


def analyse_and_plan(
    sources: list[SourceInput],
    *,
    seed: int,
    controls: dict[str, float] | None = None,
    duration_s: float = 45.0,
    role_overrides: dict[str, str] | None = None,
    mode: str = "legacy",
    tonal_strategy: str = "contour",
    groove_q: float | None = None,
) -> tuple[dict[str, Any], dict[str, SourceAnalysis], dict[str, RoleDecision]]:
    """``role_overrides`` is keyed by source key (content hash). ``mode``: legacy (M4/M4.5 planner),
    organic or composed (M4.6 motif composer)."""
    if not sources:
        raise ValueError("at least one source is required")
    keys = [s.key for s in sources]
    if len(set(keys)) != len(keys):
        raise ValueError("duplicate sources")
    ordered = sorted(sources, key=lambda s: s.key)
    for s in ordered:
        if s.sample_rate != SR:
            raise ValueError(f"source {s.key[:8]} is {s.sample_rate} Hz; canonical rate is {SR}")
    analyses = {s.key: analyze_source(s.key, s.samples, s.sample_rate, s.arrays) for s in ordered}
    overrides = role_overrides or {}
    roles = {k: assign_role(a, overrides.get(k)) for k, a in analyses.items()}
    if mode == "legacy":
        plan = plan_composition(
            list(analyses.values()), roles, seed=seed, controls=controls, duration_s=duration_s
        )
        plan["mode"] = "legacy"
    elif mode in MODES:
        materials = {
            s.key: extract_material(analyses[s.key], s.samples, s.sample_rate) for s in ordered
        }
        plan = compose_plan(
            list(analyses.values()),
            roles,
            materials,
            seed=seed,
            mode=mode,
            controls=controls,
            duration_s=duration_s,
            tonal_strategy=tonal_strategy,
            groove_q=groove_q,
        )
    else:
        raise ValueError(f"mode must be 'legacy' or one of {MODES}")
    return plan, analyses, roles


def compose(
    sources: list[SourceInput],
    *,
    seed: int,
    controls: dict[str, float] | None = None,
    duration_s: float = 45.0,
    role_overrides: dict[str, str] | None = None,
    mode: str = "legacy",
    tonal_strategy: str = "contour",
    groove_q: float | None = None,
) -> ComposeResult:
    plan, analyses, roles = analyse_and_plan(
        sources,
        seed=seed,
        controls=controls,
        duration_s=duration_s,
        role_overrides=role_overrides,
        mode=mode,
        tonal_strategy=tonal_strategy,
        groove_q=groove_q,
    )
    by_key = {s.key: s.samples for s in sources}
    stems, master, metrics = render_plan(plan, by_key)
    return ComposeResult(plan, canonical_plan_hash(plan), analyses, roles, stems, master, metrics)
