"""Repositories for compositions (M4)."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any

from unheard.storage.ids import uuid7
from unheard.storage.repos import utcnow


@dataclass(frozen=True)
class CompositionRow:
    id: str
    parent_id: str | None
    name: str
    saved: bool
    mode: str
    status: str
    error: str | None
    attempts: int
    seed: int
    planner_version: int
    render_version: int
    analysis_version: int
    dsp_version: int
    request_hash: str
    controls: dict[str, float]
    overrides: dict[str, str]
    target_duration_s: float
    duration_s: float | None
    tempo_bpm: float | None
    plan_hash: str | None
    metrics: dict[str, Any] | None
    master_path: str | None
    master_sha256: str | None
    created_at: str
    updated_at: str
    rendered_at: str | None

    @classmethod
    def from_row(cls, r: sqlite3.Row) -> CompositionRow:
        return cls(
            r["id"],
            r["parent_id"],
            r["name"],
            bool(r["saved"]),
            r["mode"],
            r["status"],
            r["error"],
            int(r["attempts"]),
            int(r["seed"]),
            int(r["planner_version"]),
            int(r["render_version"]),
            int(r["analysis_version"]),
            int(r["dsp_version"]),
            r["request_hash"],
            json.loads(r["controls_json"]),
            json.loads(r["overrides_json"]),
            float(r["target_duration_s"]),
            None if r["duration_s"] is None else float(r["duration_s"]),
            None if r["tempo_bpm"] is None else float(r["tempo_bpm"]),
            r["plan_hash"],
            json.loads(r["metrics_json"]) if r["metrics_json"] else None,
            r["master_path"],
            r["master_sha256"],
            r["created_at"],
            r["updated_at"],
            r["rendered_at"],
        )


class CompositionRepo:
    @staticmethod
    def insert(
        conn: sqlite3.Connection,
        *,
        parent_id: str | None,
        name: str,
        seed: int,
        versions: dict[str, int],
        request_hash: str,
        controls: dict[str, float],
        overrides: dict[str, str],
        target_duration_s: float,
        sources: list[dict[str, str]],
        mode: str = "legacy",
    ) -> str:
        cid = uuid7()
        now = utcnow()
        conn.execute(
            "INSERT INTO composition (id,parent_id,name,saved,mode,status,seed,planner_version,"
            "render_version,analysis_version,dsp_version,request_hash,controls_json,overrides_json,"
            "target_duration_s,created_at,updated_at) VALUES (?,?,?,0,?,'queued',?,?,?,?,?,?,?,?,?,?,?)",
            (
                cid,
                parent_id,
                name,
                mode,
                seed,
                versions["planner"],
                versions["render"],
                versions["analysis"],
                versions["dsp"],
                request_hash,
                json.dumps(controls),
                json.dumps(overrides),
                target_duration_s,
                now,
                now,
            ),
        )
        for i, s in enumerate(sources):
            conn.execute(
                "INSERT INTO composition_source (composition_id, position, recording_id, content_hash) "
                "VALUES (?,?,?,?)",
                (cid, i, s["recording_id"], s["content_hash"]),
            )
        return cid

    @staticmethod
    def get(conn: sqlite3.Connection, cid: str) -> CompositionRow | None:
        r = conn.execute("SELECT * FROM composition WHERE id=?", (cid,)).fetchone()
        return CompositionRow.from_row(r) if r else None

    @staticmethod
    def by_request(conn: sqlite3.Connection, request_hash: str) -> CompositionRow | None:
        r = conn.execute(
            "SELECT * FROM composition WHERE request_hash=? AND status!='failed' "
            "ORDER BY created_at DESC LIMIT 1",
            (request_hash,),
        ).fetchone()
        return CompositionRow.from_row(r) if r else None

    @staticmethod
    def all(conn: sqlite3.Connection, *, recording_id: str | None = None) -> list[CompositionRow]:
        if recording_id:
            rows = conn.execute(
                "SELECT c.* FROM composition c WHERE c.id IN "
                "(SELECT composition_id FROM composition_source WHERE recording_id=?) "
                "ORDER BY c.created_at DESC",
                (recording_id,),
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM composition ORDER BY created_at DESC").fetchall()
        return [CompositionRow.from_row(r) for r in rows]

    @staticmethod
    def sources(conn: sqlite3.Connection, cid: str) -> list[dict[str, Any]]:
        rows = conn.execute(
            "SELECT * FROM composition_source WHERE composition_id=? ORDER BY position", (cid,)
        ).fetchall()
        return [
            {
                "position": r["position"],
                "recording_id": r["recording_id"],
                "content_hash": r["content_hash"],
                "role": r["role"],
                "secondary_role": r["secondary_role"],
                "decision": json.loads(r["decision_json"]) if r["decision_json"] else None,
                "analysis": json.loads(r["analysis_json"]) if r["analysis_json"] else None,
            }
            for r in rows
        ]

    @staticmethod
    def tracks(conn: sqlite3.Connection, cid: str) -> list[dict[str, Any]]:
        rows = conn.execute(
            "SELECT * FROM composition_track WHERE composition_id=? ORDER BY layer_order", (cid,)
        ).fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    def events(conn: sqlite3.Connection, cid: str) -> list[dict[str, Any]]:
        rows = conn.execute(
            "SELECT * FROM composition_event WHERE composition_id=? ORDER BY seq", (cid,)
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["params"] = json.loads(d.pop("params_json"))
            out.append(d)
        return out

    @staticmethod
    def plan(conn: sqlite3.Connection, cid: str) -> dict[str, Any] | None:
        r = conn.execute("SELECT plan_json FROM composition WHERE id=?", (cid,)).fetchone()
        return json.loads(r["plan_json"]) if r and r["plan_json"] else None

    @staticmethod
    def set_processing(conn: sqlite3.Connection, cid: str) -> None:
        conn.execute(
            "UPDATE composition SET status='processing', attempts=attempts+1, error=NULL, updated_at=? "
            "WHERE id=?",
            (utcnow(), cid),
        )

    @staticmethod
    def set_failed(conn: sqlite3.Connection, cid: str, error: str) -> None:
        conn.execute(
            "UPDATE composition SET status='failed', error=?, updated_at=? WHERE id=?",
            (error[:2000], utcnow(), cid),
        )

    @staticmethod
    def requeue(conn: sqlite3.Connection, cid: str) -> None:
        conn.execute(
            "UPDATE composition SET status='queued', error=NULL, updated_at=? WHERE id=?",
            (utcnow(), cid),
        )

    @staticmethod
    def next_queued(conn: sqlite3.Connection) -> str | None:
        r = conn.execute(
            "SELECT id FROM composition WHERE status='queued' ORDER BY created_at LIMIT 1"
        ).fetchone()
        return str(r["id"]) if r else None

    @staticmethod
    def reset_processing(conn: sqlite3.Connection) -> int:
        cur = conn.execute(
            "UPDATE composition SET status='queued', updated_at=? WHERE status='processing'",
            (utcnow(),),
        )
        return int(cur.rowcount)

    @staticmethod
    def complete(
        conn: sqlite3.Connection,
        cid: str,
        *,
        plan: dict[str, Any],
        plan_hash: str,
        metrics: dict[str, Any],
        master_path: str,
        master_sha256: str,
        duration_s: float,
        sources: list[dict[str, Any]],
        tracks: list[dict[str, Any]],
        events: list[dict[str, Any]],
    ) -> None:
        now = utcnow()
        conn.execute("DELETE FROM composition_track WHERE composition_id=?", (cid,))
        conn.execute("DELETE FROM composition_event WHERE composition_id=?", (cid,))
        for s in sources:
            conn.execute(
                "UPDATE composition_source SET role=?, secondary_role=?, decision_json=?, "
                "analysis_json=? WHERE composition_id=? AND content_hash=?",
                (
                    s["role"],
                    s["secondary_role"],
                    json.dumps(s["decision"]),
                    json.dumps(s["analysis"]),
                    cid,
                    s["content_hash"],
                ),
            )
        for t in tracks:
            conn.execute(
                "INSERT INTO composition_track (id, composition_id, track_key, recording_id, content_hash,"
                " role, layer_order, pan, enters, stem_path, stem_sha256) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    uuid7(),
                    cid,
                    t["track_key"],
                    t["recording_id"],
                    t["content_hash"],
                    t["role"],
                    t["layer_order"],
                    t["pan"],
                    t["enters"],
                    t["stem_path"],
                    t["stem_sha256"],
                ),
            )
        for e in events:
            conn.execute(
                "INSERT INTO composition_event (composition_id, seq, track_key, recording_id, kind, role,"
                " section, comp_start_s, comp_dur_s, source_start_s, source_end_s, params_json)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    cid,
                    e["seq"],
                    e["track_key"],
                    e["recording_id"],
                    e["kind"],
                    e["role"],
                    e["section"],
                    e["comp_start_s"],
                    e["comp_dur_s"],
                    e["source_start_s"],
                    e["source_end_s"],
                    json.dumps(e["params"]),
                ),
            )
        conn.execute(
            "UPDATE composition SET status='ready', error=NULL, plan_json=?, plan_hash=?, metrics_json=?,"
            " master_path=?, master_sha256=?, duration_s=?, tempo_bpm=?, rendered_at=?, updated_at=? WHERE id=?",
            (
                json.dumps(plan),
                plan_hash,
                json.dumps(metrics),
                master_path,
                master_sha256,
                duration_s,
                plan["tempo_bpm"],
                now,
                now,
                cid,
            ),
        )

    @staticmethod
    def patch(conn: sqlite3.Connection, cid: str, *, name: str | None, saved: bool | None) -> None:
        if name is not None:
            conn.execute(
                "UPDATE composition SET name=?, updated_at=? WHERE id=?", (name, utcnow(), cid)
            )
        if saved is not None:
            conn.execute(
                "UPDATE composition SET saved=?, updated_at=? WHERE id=?",
                (int(saved), utcnow(), cid),
            )

    @staticmethod
    def delete(conn: sqlite3.Connection, cid: str) -> None:
        conn.execute("DELETE FROM composition WHERE id=?", (cid,))

    @staticmethod
    def ids_for_recording(conn: sqlite3.Connection, recording_id: str) -> list[str]:
        rows = conn.execute(
            "SELECT DISTINCT composition_id FROM composition_source WHERE recording_id=?",
            (recording_id,),
        ).fetchall()
        return [str(r["composition_id"]) for r in rows]
