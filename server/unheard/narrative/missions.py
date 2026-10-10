"""Adaptive field missions: deterministic candidates from real gaps in the player's memory, deterministic completion.

Gemma may reorder/reword the candidates (see service) but can neither add objectives nor judge completion. Missions never
ask for a place, coordinates, approaching animals or recording people.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from unheard.narrative.facts import Ref, sanitize_text
from unheard.narrative.state import ACT_TARGET_TEACH, Ann, Snapshot, act_flags

MAX_ACTIVE = 2
MAX_CANDIDATES = 4
NOVELTY_MAX_COSINE = 0.75
PULSE_MIN_ONSETS_PER_S = 0.8
PITCHED_MIN_VOICED_RATIO = 0.20

SAFETY = "Stay on public paths. Keep your distance from animals. Do not record people without their consent."
FALLBACK = "If nothing like that is within easy reach, skip this mission; it will wait."
MECHANICAL = re.compile(
    r"engine|motor|machine|vacuum|clock|tick|siren|train|plane|airplane|aircraft|helicopter|drill|\bsaw\b|\bfan\b|hum\b|"
    r"keyboard|typing|mouse|washing|blender|traffic|truck|generator|\bcar\b|vehicle|appliance|chainsaw|tool",
    re.I,
)

TYPES = (
    "record_first",
    "gather_three",
    "resolve_unknown",
    "second_example",
    "novel_sound",
    "repeat_not_machine",
    "find_tonal",
)
PRIORITY = {
    "record_first": 0,
    "resolve_unknown": 1,
    "gather_three": 2,
    "second_example": 3,
    "repeat_not_machine": 4,
    "find_tonal": 5,
    "novel_sound": 6,
}


def mission_id(kind: str, key: str) -> str:
    return "msn_" + hashlib.sha256(f"{kind}|{key}".encode()).hexdigest()[:12]


@dataclass
class MissionContext:
    """Measurements the generator/evaluator need; injected so the logic stays testable and the model never sees them."""

    onset_density: Callable[[str], float | None]  # recording id -> onsets per second
    voiced_ratio: Callable[[str], float | None]  # recording id -> share of pitched frames
    max_cosine: Callable[
        [str, list[str]], float | None
    ]  # recording vs baseline recordings (None = unavailable)
    centroid_hz: Callable[[str], float | None] = lambda _r: None  # DSP fallback for novelty
    label_names: dict[str, str] = field(default_factory=dict)


@dataclass
class Candidate:
    id: str
    type: str
    title: str
    objective: str
    reason: str
    evidence: list[Ref]
    completion: dict[str, str]
    params: dict[str, Any]

    def public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "title": self.title,
            "objective": self.objective,
            "reason": self.reason,
            "evidence": [e.to_json() for e in self.evidence],
            "completion": self.completion,
            "safe_fallback": FALLBACK,
            "safety": SAFETY,
        }


def _is_mechanical(snap: Snapshot, a: Ann) -> bool:
    return any(MECHANICAL.search(snap.label_names.get(lid, "")) for lid in a.label_ids)


def generate_candidates(snap: Snapshot, ctx: MissionContext) -> list[Candidate]:
    out: list[Candidate] = []
    flags = act_flags(snap)
    taught = snap.taught
    if not snap.recs:
        out.append(
            Candidate(
                mission_id("record_first", "start"),
                "record_first",
                "A first sound",
                "Record about ten seconds of any sound you can safely reach.",
                "ECHO-0 has no recording yet.",
                [],
                {
                    "predicate": "new_recording",
                    "description": "A new recording finishes processing.",
                },
                {},
            )
        )
        return out

    if snap.unknown_unresolved:
        ids = sorted(snap.unknown_unresolved)[:3]
        out.append(
            Candidate(
                mission_id("resolve_unknown", ids[0]),
                "resolve_unknown",
                "A sound without a name",
                "Give a name to a recording ECHO-0 could not name.",
                f"{len(snap.unknown_unresolved)} recording(s) are still unnamed.",
                [Ref("recording", i, None, "system") for i in ids],
                {
                    "predicate": "target_annotated",
                    "description": "One of those recordings gets a name from you.",
                },
                {"recording_ids": ids},
            )
        )

    if not flags["act_2"]:
        out.append(
            Candidate(
                mission_id("gather_three", "teach"),
                "gather_three",
                "Teach three sounds",
                "Teach ECHO-0 three sounds by naming three recordings.",
                f"{len(taught)} of {ACT_TARGET_TEACH} recordings are taught.",
                [Ref("measurement", "taught_count:all", None, "system")],
                {
                    "predicate": "taught_count",
                    "description": f"{ACT_TARGET_TEACH} recordings carry a name from you.",
                },
                {"target": ACT_TARGET_TEACH},
            )
        )

    # a label with exactly one taught example
    by_label: dict[str, list[Ann]] = {}
    for a in taught:
        for lid in a.label_ids:
            by_label.setdefault(lid, []).append(a)
    singles = sorted(
        (lid for lid, anns in by_label.items() if len(anns) == 1),
        key=lambda lid: (by_label[lid][0].created_at, lid),
    )
    if singles:
        lid = singles[0]
        name = sanitize_text(ctx.label_names.get(lid)) or "that sound"
        out.append(
            Candidate(
                mission_id("second_example", lid),
                "second_example",
                f"Another '{name}'",
                f"Record another sound that you would name '{name}'.",
                f"'{name}' has only one taught example.",
                [
                    Ref("label", lid, name, "user_confirmed"),
                    Ref("recording", by_label[lid][0].recording_id, None, "user_confirmed"),
                ],
                {
                    "predicate": "new_recording_with_label",
                    "description": f"A new recording you name '{name}'.",
                },
                {"label_id": lid, "label": name},
            )
        )

    # rhythmic taught sounds that are all mechanical -> ask for an organic repeater
    pulsed = [
        a for a in taught if (ctx.onset_density(a.recording_id) or 0.0) >= PULSE_MIN_ONSETS_PER_S
    ]
    if len(pulsed) >= 2 and all(_is_mechanical(snap, a) for a in pulsed):
        ids = sorted(a.recording_id for a in pulsed)[:4]
        out.append(
            Candidate(
                mission_id("repeat_not_machine", ids[0]),
                "repeat_not_machine",
                "A repeating sound that is not a machine",
                "Record a sound that repeats on its own rhythm and is not an engine or appliance.",
                f"{len(pulsed)} of your taught sounds repeat, and all of them are mechanical.",
                [Ref("measurement", f"mechanical_pulse:{i}", None, "measurement") for i in ids],
                {
                    "predicate": "new_recording_matching",
                    "description": f"A new recording with a steady pulse (at least {PULSE_MIN_ONSETS_PER_S} onsets per second) that you name with a non-mechanical word.",
                },
                {"min_onsets_per_s": PULSE_MIN_ONSETS_PER_S},
            )
        )

    if len(taught) >= 2:
        voiced = [ctx.voiced_ratio(a.recording_id) for a in taught]
        measured = [v for v in voiced if v is not None]
        if measured and max(measured) < PITCHED_MIN_VOICED_RATIO:
            out.append(
                Candidate(
                    mission_id("find_tonal", f"{len(taught)}"),
                    "find_tonal",
                    "A sound with a pitch",
                    "Record a sound that has a clear pitch: something you could hum along to.",
                    "None of your taught sounds has a clear pitch; they are all broadband.",
                    [Ref("measurement", "voiced_ratio:taught", None, "measurement")],
                    {
                        "predicate": "new_recording_matching",
                        "description": f"A new, named recording that is pitched at least {int(PITCHED_MIN_VOICED_RATIO * 100)}% of the time.",
                    },
                    {"min_voiced_ratio": PITCHED_MIN_VOICED_RATIO},
                )
            )

    if len(taught) >= 1:
        out.append(
            Candidate(
                mission_id("novel_sound", f"{len(taught)}"),
                "novel_sound",
                "Something unlike the rest",
                "Record a sound that is unlike anything you have taught ECHO-0 so far.",
                f"{len(taught)} recording(s) are taught; a very different one would widen the memory.",
                [Ref("measurement", "memory:novelty", None, "measurement")],
                {
                    "predicate": "new_recording_novel",
                    "description": f"A new recording whose closest taught sound is far away (similarity at most {NOVELTY_MAX_COSINE}).",
                },
                {"max_cosine": NOVELTY_MAX_COSINE},
            )
        )

    out.sort(key=lambda c: (PRIORITY[c.type], c.id))
    return out[:MAX_CANDIDATES]


def evaluate(snap: Snapshot, ctx: MissionContext, row: dict[str, Any]) -> dict[str, Any]:
    """Deterministic completion for an active mission row -> {status, progress, completed_at, evidence}."""
    kind = row["type"]
    params = row["params"]
    baseline = set(row["baseline"].get("recording_ids", []))
    new_recs = [r for r in snap.recs.values() if r.id not in baseline]
    taught_ids = {a.recording_id: a for a in snap.taught}
    done_at: str | None = None
    evid: list[dict[str, Any]] = []
    progress: dict[str, int] | None = None
    status = "active"

    def finish(at: str, rec_id: str | None) -> None:
        nonlocal done_at, evid
        done_at = at
        evid = [Ref("recording", rec_id, None, "measurement").to_json()] if rec_id else []

    if kind == "record_first":
        if new_recs:
            finish(new_recs[0].created_at, new_recs[0].id)
    elif kind == "gather_three":
        progress = {"current": min(len(snap.taught), params["target"]), "target": params["target"]}
        if len(snap.taught) >= params["target"]:
            finish(snap.taught[params["target"] - 1].created_at, None)
    elif kind == "resolve_unknown":
        targets = [t for t in params["recording_ids"] if t in snap.recs]
        if not targets:
            status = "expired"
        for t in targets:
            a = snap.active.get(t)
            if a is not None and not a.is_unknown and a.label_ids:
                finish(a.created_at, t)
                break
    elif kind == "second_example":
        for r in new_recs:
            a = taught_ids.get(r.id)
            if a is not None and params["label_id"] in a.label_ids:
                finish(a.created_at, r.id)
                break
        if done_at is None and not any(params["label_id"] in a.label_ids for a in snap.taught):
            status = "expired"
    elif kind == "novel_sound":
        for r in new_recs:
            sim = ctx.max_cosine(r.id, sorted(baseline & set(snap.recs)))
            if sim is not None and sim <= params["max_cosine"]:
                finish(r.created_at, r.id)
                break
    elif kind == "repeat_not_machine":
        for r in new_recs:
            a = taught_ids.get(r.id)
            if a is None or _is_mechanical(snap, a):
                continue
            if (ctx.onset_density(r.id) or 0.0) >= params["min_onsets_per_s"]:
                finish(a.created_at, r.id)
                break
    elif kind == "find_tonal":
        for r in new_recs:
            a = taught_ids.get(r.id)
            vr = ctx.voiced_ratio(r.id)
            if a is not None and vr is not None and vr >= params["min_voiced_ratio"]:
                finish(a.created_at, r.id)
                break
    if done_at is not None:
        status = "completed"
    return {"status": status, "progress": progress, "completed_at": done_at, "evidence": evid}


def row_from_db(r: Any) -> dict[str, Any]:
    return {
        "id": r["id"],
        "type": r["type"],
        "status": r["status"],
        "params": json.loads(r["params_json"]),
        "baseline": json.loads(r["baseline_json"]),
        "snapshot": json.loads(r["snapshot_json"]),
        "activated_at": r["activated_at"],
        "completed_at": r["completed_at"],
        "completion_evidence": json.loads(r["completion_evidence_json"])
        if r["completion_evidence_json"]
        else [],
    }
