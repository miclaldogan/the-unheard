"""Authoritative narrative state, derived from persisted records (layer 1: no model involved).

Everything here is a pure function of the database. A player who already has recordings, annotations and compositions is
placed correctly without replaying a tutorial; deleting data can move the player back; nothing can be "unlocked" by prose.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from unheard.narrative import CONTRACT_VERSION
from unheard.narrative.facts import Ref

ACT_TARGET_TEACH = 3
ACT_TARGET_ORCHESTRA = 3
ACTS = ("prologue", "act_1", "act_2", "act_3", "ending")
ACT_TITLES = {
    "prologue": "Silence",
    "act_1": "The First Sound",
    "act_2": "Teach the Machine",
    "act_3": "The World Remembered",
}
MILESTONE_TITLES = {
    "first_recording": ("A first recording", False),
    "first_hearing": ("First hearing", False),
    "first_teaching": ("A first teaching", False),
    "third_teaching": ("Three sounds taught", False),
    "first_memory_influence": ("Memory consulted", False),
    "first_correction": ("A first correction", True),
    "unknown_met": ("A sound without a name", True),
    "unknown_resolved": ("A nameless sound named", True),
    "first_composition": ("A first composition", False),
    "orchestra_of_three": ("An orchestra of three", False),
    "ending_reached": ("The world remembered", False),
}


def utcnow() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


@dataclass
class Rec:
    id: str
    created_at: str
    duration_s: float
    content_hash: str


@dataclass
class Ann:
    id: str
    recording_id: str
    action: str
    status: str
    label_ids: list[str]
    is_unknown: bool
    descriptors: list[str]
    prediction_id: str | None
    created_at: str


@dataclass
class Comp:
    id: str
    created_at: str
    rendered_at: str | None
    mode: str
    source_ids: list[str]
    annotated_source_ids: list[str]


@dataclass
class Snapshot:
    now: str
    model_enabled: bool
    memory_version: int
    recs: dict[str, Rec]  # ready, existing recordings
    heard_at: dict[str, str]  # recording id -> first base prediction time
    active: dict[str, Ann]  # recording id -> active annotation
    taught: list[Ann]  # active, non-unknown, with labels (chronological)
    corrections: list[Ann]  # every correct annotation of an existing recording
    unknown_unresolved: list[str]  # recording ids
    unknown_met_at: str | None
    unknown_resolved_at: str | None
    memory_influence_at: str | None
    comps: list[Comp]  # ready compositions, chronological
    label_names: dict[str, str]
    latest_fused: dict[str, dict[str, Any]] = field(
        default_factory=dict
    )  # recording id -> {created_at, memory_version, novelty, results}


def _rows(conn: sqlite3.Connection, sql: str, args: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
    return list(conn.execute(sql, args).fetchall())


def derive_snapshot(conn: sqlite3.Connection, *, model_enabled: bool) -> Snapshot:
    recs = {
        r["id"]: Rec(r["id"], r["created_at"], float(r["duration_s"]), r["content_hash"])
        for r in _rows(
            conn,
            "SELECT id, created_at, duration_s, content_hash FROM recording "
            "WHERE status='ready' AND deleted_at IS NULL ORDER BY created_at, id",
        )
    }
    heard_at = {
        r[0]: r[1]
        for r in conn.execute(
            "SELECT p.recording_id, MIN(p.created_at) FROM prediction p JOIN recording r ON r.id=p.recording_id "
            "WHERE p.kind='base' AND r.deleted_at IS NULL GROUP BY p.recording_id"
        ).fetchall()
        if r[0] in recs
    }

    def ann(r: sqlite3.Row) -> Ann:
        return Ann(
            r["id"],
            r["recording_id"],
            r["action"],
            r["status"],
            json.loads(r["label_ids_json"]),
            bool(r["is_unknown"]),
            json.loads(r["descriptors_json"]),
            r["prediction_id"],
            r["created_at"],
        )

    active_rows = [
        ann(r)
        for r in _rows(
            conn, "SELECT * FROM annotation WHERE status='active' ORDER BY created_at, id"
        )
    ]
    active = {a.recording_id: a for a in active_rows if a.recording_id in recs}
    taught = sorted(
        (a for a in active.values() if not a.is_unknown and a.label_ids),
        key=lambda a: (a.created_at, a.id),
    )
    corrections = [
        ann(r)
        for r in _rows(
            conn, "SELECT * FROM annotation WHERE action='correct' ORDER BY created_at, id"
        )
        if r["recording_id"] in recs
    ]

    latest_fused: dict[str, dict[str, Any]] = {}
    for r in _rows(conn, "SELECT * FROM prediction WHERE kind='fused' ORDER BY created_at, id"):
        if r["recording_id"] in recs:
            latest_fused[r["recording_id"]] = {
                "id": r["id"],
                "created_at": r["created_at"],
                "memory_version": int(r["memory_version"]),
                "novelty": json.loads(r["novelty_json"]) if r["novelty_json"] else None,
                "results": json.loads(r["results_json"]),
            }

    # unknown: the player said "I can't name it", or the system flagged it novel and nothing names it yet
    unresolved: list[str] = []
    met: list[str] = []
    for rid in recs:
        a = active.get(rid)
        fused_novel = bool((latest_fused.get(rid, {}).get("novelty") or {}).get("novel"))
        if a is not None and a.is_unknown:
            unresolved.append(rid)
            met.append(a.created_at)
        elif a is None and fused_novel:
            unresolved.append(rid)
            met.append(latest_fused[rid]["created_at"])
    resolved_at: list[str] = []
    for r in _rows(
        conn,
        "SELECT a.recording_id, a.created_at FROM annotation a WHERE a.status='active' AND a.is_unknown=0 AND EXISTS "
        "(SELECT 1 FROM annotation u WHERE u.recording_id=a.recording_id AND u.is_unknown=1 AND u.created_at<a.created_at)",
    ):
        if r["recording_id"] in recs:
            resolved_at.append(r["created_at"])
            met.append(r["created_at"])
    for r in _rows(
        conn,
        "SELECT a.recording_id, a.created_at, p.novelty_json FROM annotation a JOIN prediction p ON p.id=a.prediction_id "
        "WHERE a.action='create' AND a.status IN ('active','superseded')",
    ):
        if (
            r["recording_id"] in recs
            and r["novelty_json"]
            and json.loads(r["novelty_json"]).get("novel")
        ):
            resolved_at.append(r["created_at"])
            met.append(r["created_at"])

    influence = [
        f["created_at"]
        for f in latest_fused.values()
        if f["memory_version"] >= 1
        and (f["novelty"] or {}).get("nearest_exemplar_similarity") is not None
    ]

    comps: list[Comp] = []
    for r in _rows(
        conn,
        "SELECT id, created_at, rendered_at, mode FROM composition WHERE status='ready' ORDER BY created_at, id",
    ):
        sources = [
            s["recording_id"]
            for s in _rows(
                conn,
                "SELECT recording_id FROM composition_source WHERE composition_id=? ORDER BY position",
                (r["id"],),
            )
            if s["recording_id"] in recs
        ]
        annotated = [
            rid
            for rid in sources
            if rid in active and not active[rid].is_unknown and active[rid].label_ids
        ]
        comps.append(
            Comp(r["id"], r["created_at"], r["rendered_at"], r["mode"], sources, annotated)
        )

    names = {r["id"]: r["name"] for r in _rows(conn, "SELECT id, name FROM label")}
    mv = conn.execute("SELECT value_json FROM memory_meta WHERE key='memory_version'").fetchone()
    return Snapshot(
        now=utcnow(),
        model_enabled=model_enabled,
        memory_version=int(json.loads(mv[0])) if mv else 0,
        recs=recs,
        heard_at=heard_at,
        active=active,
        taught=taught,
        corrections=corrections,
        unknown_unresolved=unresolved,
        unknown_met_at=min(met) if met else None,
        unknown_resolved_at=min(resolved_at) if resolved_at else None,
        memory_influence_at=min(influence) if influence else None,
        comps=comps,
        label_names=names,
        latest_fused=latest_fused,
    )


def qualifying_composition(s: Snapshot) -> Comp | None:
    """Act III: a ready composition whose sources are >= 3 existing, annotated recordings."""
    for c in s.comps:
        if len(c.annotated_source_ids) >= ACT_TARGET_ORCHESTRA:
            return c
    return None


def act_flags(s: Snapshot) -> dict[str, bool]:
    first_recording = bool(s.recs)
    first_heard = bool(s.heard_at) or (first_recording and not s.model_enabled)
    act1_done = first_recording and first_heard
    act2_done = act1_done and len(s.taught) >= ACT_TARGET_TEACH
    act3_done = act2_done and qualifying_composition(s) is not None
    return {"prologue": first_recording, "act_1": act1_done, "act_2": act2_done, "act_3": act3_done}


def current_act(s: Snapshot) -> tuple[str, str]:
    f = act_flags(s)
    if not f["prologue"]:
        return "prologue", "awaiting_sound"
    if not f["act_1"]:
        return "act_1", "first_hearing"
    if not f["act_2"]:
        return "act_2", "teaching"
    if not f["act_3"]:
        return "act_3", ("composing" if s.comps else "ready_to_compose")
    return "ending", "remembered"


def _ref(type_: str, id_: str, label: str | None = None, prov: str = "system") -> dict[str, Any]:
    return Ref(type_, id_, label, prov).to_json()


def milestones(s: Snapshot) -> list[dict[str, Any]]:
    recs = list(s.recs.values())
    qual = qualifying_composition(s)
    third = s.taught[ACT_TARGET_TEACH - 1] if len(s.taught) >= ACT_TARGET_TEACH else None
    first_comp = s.comps[0] if s.comps else None
    big = next((c for c in s.comps if len(c.source_ids) >= ACT_TARGET_ORCHESTRA), None)
    heard_first = min(s.heard_at.items(), key=lambda kv: kv[1]) if s.heard_at else None
    items: dict[str, tuple[str | None, list[dict[str, Any]]]] = {
        "first_recording": (
            recs[0].created_at if recs else None,
            [_ref("recording", recs[0].id)] if recs else [],
        ),
        "first_hearing": (
            heard_first[1]
            if heard_first
            else (recs[0].created_at if recs and not s.model_enabled else None),
            [_ref("recording", heard_first[0], None, "model")]
            if heard_first
            else ([_ref("recording", recs[0].id)] if recs and not s.model_enabled else []),
        ),
        "first_teaching": (
            s.taught[0].created_at if s.taught else None,
            [_ref("annotation", s.taught[0].id, None, "user_confirmed")] if s.taught else [],
        ),
        "third_teaching": (
            third.created_at if third else None,
            [_ref("annotation", third.id, None, "user_confirmed")] if third else [],
        ),
        "first_memory_influence": (s.memory_influence_at, []),
        "first_correction": (
            s.corrections[0].created_at if s.corrections else None,
            [_ref("annotation", s.corrections[0].id, None, "user_confirmed")]
            if s.corrections
            else [],
        ),
        "unknown_met": (s.unknown_met_at, []),
        "unknown_resolved": (s.unknown_resolved_at, []),
        "first_composition": (
            first_comp.rendered_at or first_comp.created_at if first_comp else None,
            [_ref("composition", first_comp.id, None, "measurement")] if first_comp else [],
        ),
        "orchestra_of_three": (
            big.rendered_at or big.created_at if big else None,
            [_ref("composition", big.id, None, "measurement")] if big else [],
        ),
        "ending_reached": (
            qual.rendered_at or qual.created_at if qual else None,
            [_ref("composition", qual.id, None, "measurement")]
            if qual and act_flags(s)["act_3"]
            else [],
        ),
    }
    out = []
    for mid, (title_opt) in MILESTONE_TITLES.items():
        at, ev = items[mid]
        achieved = at is not None and (mid != "ending_reached" or act_flags(s)["act_3"])
        out.append(
            {
                "id": mid,
                "title": title_opt[0],
                "achieved": achieved,
                "achieved_at": at if achieved else None,
                "optional": title_opt[1],
                "evidence": ev if achieved else [],
            }
        )
    return out


def build_state(s: Snapshot, gemma: dict[str, Any]) -> dict[str, Any]:
    flags = act_flags(s)
    act, phase = current_act(s)
    ms = {m["id"]: m for m in milestones(s)}
    qual = qualifying_composition(s)
    best_comp_sources = max((len(c.annotated_source_ids) for c in s.comps), default=0)

    def status(act_id: str) -> str:
        if flags.get(act_id):
            return "complete"
        return "active" if act == act_id else "locked"

    acts = [
        {
            "id": "prologue",
            "title": ACT_TITLES["prologue"],
            "status": status("prologue"),
            "progress": {"current": min(1, len(s.recs)), "target": 1},
            "criteria": [
                {
                    "id": "first_recording",
                    "text": "A first recording finishes processing.",
                    "met": flags["prologue"],
                    "evidence": ms["first_recording"]["evidence"],
                }
            ],
        },
        {
            "id": "act_1",
            "title": ACT_TITLES["act_1"],
            "status": status("act_1"),
            "progress": {"current": 1 if flags["act_1"] else 0, "target": 1},
            "criteria": [
                {
                    "id": "first_hearing",
                    "text": "The first recording was processed and heard.",
                    "met": flags["act_1"],
                    "evidence": ms["first_hearing"]["evidence"],
                }
            ],
        },
        {
            "id": "act_2",
            "title": ACT_TITLES["act_2"],
            "status": status("act_2"),
            "progress": {
                "current": min(len(s.taught), ACT_TARGET_TEACH),
                "target": ACT_TARGET_TEACH,
            },
            "criteria": [
                {
                    "id": "third_teaching",
                    "text": "Teach ECHO-0 three sounds.",
                    "met": flags["act_2"],
                    "evidence": ms["third_teaching"]["evidence"],
                }
            ],
        },
        {
            "id": "act_3",
            "title": ACT_TITLES["act_3"],
            "status": status("act_3"),
            "progress": {"current": 1 if flags["act_3"] else 0, "target": 1},
            "criteria": [
                {
                    "id": "orchestra_of_three",
                    "text": "Compose an orchestra from three taught sounds.",
                    "met": flags["act_3"],
                    "evidence": ms["ending_reached"]["evidence"],
                }
            ],
        },
    ]
    del best_comp_sources
    return {
        "contract_version": CONTRACT_VERSION,
        "derived_at": s.now,
        "act": act,
        "phase": phase,
        "ending_unlocked": act == "ending",
        "acts": acts,
        "milestones": list(ms.values()),
        "counts": {
            "recordings": len(s.recs),
            "heard": len(s.heard_at),
            "taught": len(s.taught),
            "labels_confirmed": len({lid for a in s.taught for lid in a.label_ids}),
            "corrections": len(s.corrections),
            "unknown": len(s.unknown_unresolved),
            "compositions": len(s.comps),
            "memory_version": s.memory_version,
        },
        "gemma": gemma,
        "_qualifying_composition_id": qual.id if qual else None,
    }


# ----------------------------------------------------------------------------------------- moments


def current_moment(s: Snapshot) -> dict[str, Any]:
    """The narrative moment the player is in. Priority is act-aware; within an act the newest real event wins."""
    act, _phase = current_act(s)
    qual = qualifying_composition(s)
    if act == "ending" and qual is not None:
        return {
            "kind": "ending",
            "key": f"ending:{qual.id}",
            "act": "ending",
            "occurred_at": qual.rendered_at or qual.created_at,
            "composition_id": qual.id,
        }
    if not s.recs:
        return {
            "kind": "awaiting_sound",
            "key": "awaiting_sound",
            "act": "prologue",
            "occurred_at": s.now,
        }
    if act == "act_3":
        if s.comps:
            c = s.comps[-1]
            return {
                "kind": "composition",
                "key": f"composition:{c.id}",
                "act": "act_3",
                "occurred_at": c.rendered_at or c.created_at,
                "composition_id": c.id,
            }
        return {
            "kind": "ready_to_compose",
            "key": f"ready_to_compose:{len(s.taught)}",
            "act": "act_3",
            "occurred_at": s.taught[ACT_TARGET_TEACH - 1].created_at,
        }
    cands: list[tuple[str, dict[str, Any]]] = []
    for a in s.taught:
        kind = "correction" if a.action == "correct" else "teaching"
        cands.append(
            (
                a.created_at,
                {
                    "kind": kind,
                    "key": f"annotation:{a.id}",
                    "annotation_id": a.id,
                    "recording_id": a.recording_id,
                },
            )
        )
    for rid in s.unknown_unresolved:
        ua = s.active.get(rid)
        t = ua.created_at if ua else s.latest_fused[rid]["created_at"]
        cands.append((t, {"kind": "unknown", "key": f"unknown:{rid}", "recording_id": rid}))
    for rid, f in s.latest_fused.items():
        nov = f["novelty"] or {}
        if (
            rid not in s.active
            and nov.get("nearest_exemplar_similarity") is not None
            and not nov.get("novel")
            and f["memory_version"] >= 1
        ):
            cands.append(
                (
                    f["created_at"],
                    {"kind": "relationship", "key": f"relationship:{rid}", "recording_id": rid},
                )
            )
    if s.heard_at or (s.recs and not s.model_enabled):
        first = (
            min(s.heard_at.items(), key=lambda kv: kv[1])
            if s.heard_at
            else (next(iter(s.recs)), s.recs[next(iter(s.recs))].created_at)
        )
        cands.append(
            (
                first[1],
                {"kind": "first_sound", "key": f"first_sound:{first[0]}", "recording_id": first[0]},
            )
        )
    if not cands:  # recordings exist but none is heard yet
        r = next(iter(s.recs.values()))
        return {
            "kind": "first_sound",
            "key": f"first_sound:{r.id}",
            "act": act,
            "occurred_at": r.created_at,
            "recording_id": r.id,
        }
    cands.sort(key=lambda c: (c[0], c[1]["kind"] == "first_sound"))
    t, m = cands[-1]
    m.update({"act": act, "occurred_at": t})
    return m


def available_actions(s: Snapshot) -> list[str]:
    act, _ = current_act(s)
    acts = ["record"]
    if s.recs:
        acts += ["teach", "open_atlas"]
    if len(s.taught) >= 1:
        acts.append("open_orchestra")
    if act in ("act_3", "ending") or len(s.taught) >= ACT_TARGET_TEACH:
        acts.append("compose")
    return acts
