"""Typed repositories over the SQLite tables. No business logic lives here."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from unheard.storage.ids import uuid7


def utcnow() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


@dataclass(frozen=True)
class RecordingRow:
    id: str
    session_id: str | None
    content_hash: str
    source_hash: str
    created_at: str
    captured_at: str | None
    original_filename: str | None
    client_mime: str | None
    device_info: dict[str, Any] | None
    duration_s: float
    quality: dict[str, Any]
    status: str
    error: dict[str, Any] | None

    @classmethod
    def from_row(cls, r: sqlite3.Row) -> RecordingRow:
        return cls(
            id=r["id"],
            session_id=r["session_id"],
            content_hash=r["content_hash"],
            source_hash=r["source_hash"],
            created_at=r["created_at"],
            captured_at=r["captured_at"],
            original_filename=r["original_filename"],
            client_mime=r["client_mime"],
            device_info=json.loads(r["device_info_json"]) if r["device_info_json"] else None,
            duration_s=float(r["duration_s"]),
            quality=json.loads(r["quality_json"]),
            status=r["status"],
            error=json.loads(r["error_json"]) if r["error_json"] else None,
        )


@dataclass(frozen=True)
class AudioAssetRow:
    id: str
    recording_id: str
    kind: str
    path: str
    container: str | None
    codec: str | None
    sample_rate: int
    channels: int
    sample_format: str | None
    bytes: int

    @classmethod
    def from_row(cls, r: sqlite3.Row) -> AudioAssetRow:
        return cls(
            id=r["id"],
            recording_id=r["recording_id"],
            kind=r["kind"],
            path=r["path"],
            container=r["container"],
            codec=r["codec"],
            sample_rate=int(r["sample_rate"]),
            channels=int(r["channels"]),
            sample_format=r["sample_format"],
            bytes=int(r["bytes"]),
        )


@dataclass(frozen=True)
class FeatureSetRow:
    id: str
    recording_id: str
    dsp_version: int
    summary: dict[str, Any]
    artifact_path: str
    artifact_sha256: str
    created_at: str

    @classmethod
    def from_row(cls, r: sqlite3.Row) -> FeatureSetRow:
        return cls(
            id=r["id"],
            recording_id=r["recording_id"],
            dsp_version=int(r["dsp_version"]),
            summary=json.loads(r["summary_json"]),
            artifact_path=r["artifact_path"],
            artifact_sha256=r["artifact_sha256"],
            created_at=r["created_at"],
        )


@dataclass(frozen=True)
class JobRow:
    id: str
    recording_id: str
    stage: str
    status: str
    attempts: int
    error: str | None
    created_at: str
    updated_at: str

    @classmethod
    def from_row(cls, r: sqlite3.Row) -> JobRow:
        return cls(
            id=r["id"],
            recording_id=r["recording_id"],
            stage=r["stage"],
            status=r["status"],
            attempts=int(r["attempts"]),
            error=r["error"],
            created_at=r["created_at"],
            updated_at=r["updated_at"],
        )


class RecordingRepo:
    @staticmethod
    def insert(
        conn: sqlite3.Connection,
        *,
        id: str,
        content_hash: str,
        source_hash: str,
        duration_s: float,
        quality: dict[str, Any],
        original_filename: str | None,
        client_mime: str | None,
        captured_at: str | None,
        device_info: dict[str, Any] | None,
        session_id: str | None = None,
    ) -> None:
        conn.execute(
            """INSERT INTO recording (id, session_id, content_hash, source_hash, created_at,
               captured_at, original_filename, client_mime, device_info_json, duration_s,
               quality_json, status) VALUES (?,?,?,?,?,?,?,?,?,?,?,'uploaded')""",
            (
                id,
                session_id,
                content_hash,
                source_hash,
                utcnow(),
                captured_at,
                original_filename,
                client_mime,
                json.dumps(device_info) if device_info is not None else None,
                duration_s,
                json.dumps(quality),
            ),
        )

    @staticmethod
    def get(conn: sqlite3.Connection, id: str) -> RecordingRow | None:
        r = conn.execute(
            "SELECT * FROM recording WHERE id=? AND deleted_at IS NULL", (id,)
        ).fetchone()
        return RecordingRow.from_row(r) if r else None

    @staticmethod
    def get_by_hash(conn: sqlite3.Connection, content_hash: str) -> RecordingRow | None:
        r = conn.execute(
            "SELECT * FROM recording WHERE content_hash=? AND deleted_at IS NULL", (content_hash,)
        ).fetchone()
        return RecordingRow.from_row(r) if r else None

    @staticmethod
    def list(conn: sqlite3.Connection, *, limit: int, offset: int) -> list[RecordingRow]:
        rows = conn.execute(
            "SELECT * FROM recording WHERE deleted_at IS NULL "
            "ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
        return [RecordingRow.from_row(r) for r in rows]

    @staticmethod
    def count(conn: sqlite3.Connection) -> int:
        return int(
            conn.execute("SELECT COUNT(*) FROM recording WHERE deleted_at IS NULL").fetchone()[0]
        )

    @staticmethod
    def set_status(
        conn: sqlite3.Connection, id: str, status: str, error: dict[str, Any] | None = None
    ) -> None:
        conn.execute(
            "UPDATE recording SET status=?, error_json=? WHERE id=?",
            (status, json.dumps(error) if error is not None else None, id),
        )

    @staticmethod
    def delete(conn: sqlite3.Connection, id: str) -> None:
        conn.execute("DELETE FROM recording WHERE id=?", (id,))


class AudioAssetRepo:
    @staticmethod
    def insert(
        conn: sqlite3.Connection,
        *,
        recording_id: str,
        kind: str,
        path: str,
        container: str | None,
        codec: str | None,
        sample_rate: int,
        channels: int,
        sample_format: str | None,
        nbytes: int,
    ) -> str:
        id = uuid7()
        conn.execute(
            """INSERT INTO audio_asset (id, recording_id, kind, path, container, codec,
               sample_rate, channels, sample_format, bytes) VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                id,
                recording_id,
                kind,
                path,
                container,
                codec,
                sample_rate,
                channels,
                sample_format,
                nbytes,
            ),
        )
        return id

    @staticmethod
    def for_recording(conn: sqlite3.Connection, recording_id: str) -> list[AudioAssetRow]:
        rows = conn.execute(
            "SELECT * FROM audio_asset WHERE recording_id=? ORDER BY kind", (recording_id,)
        ).fetchall()
        return [AudioAssetRow.from_row(r) for r in rows]

    @staticmethod
    def get(conn: sqlite3.Connection, recording_id: str, kind: str) -> AudioAssetRow | None:
        r = conn.execute(
            "SELECT * FROM audio_asset WHERE recording_id=? AND kind=?", (recording_id, kind)
        ).fetchone()
        return AudioAssetRow.from_row(r) if r else None


class FeatureSetRepo:
    @staticmethod
    def upsert(
        conn: sqlite3.Connection,
        *,
        recording_id: str,
        dsp_version: int,
        summary: dict[str, Any],
        artifact_path: str,
        artifact_sha256: str,
    ) -> str:
        id = uuid7()
        conn.execute(
            """INSERT INTO feature_set (id, recording_id, dsp_version, summary_json,
               artifact_path, artifact_sha256, created_at) VALUES (?,?,?,?,?,?,?)
               ON CONFLICT(recording_id, dsp_version) DO UPDATE SET
               summary_json=excluded.summary_json, artifact_path=excluded.artifact_path,
               artifact_sha256=excluded.artifact_sha256, created_at=excluded.created_at""",
            (
                id,
                recording_id,
                dsp_version,
                json.dumps(summary),
                artifact_path,
                artifact_sha256,
                utcnow(),
            ),
        )
        return id

    @staticmethod
    def latest(conn: sqlite3.Connection, recording_id: str) -> FeatureSetRow | None:
        r = conn.execute(
            "SELECT * FROM feature_set WHERE recording_id=? ORDER BY dsp_version DESC LIMIT 1",
            (recording_id,),
        ).fetchone()
        return FeatureSetRow.from_row(r) if r else None


class JobRepo:
    @staticmethod
    def enqueue(conn: sqlite3.Connection, recording_id: str, stage: str) -> str:
        id = uuid7()
        now = utcnow()
        conn.execute(
            "INSERT INTO job (id, recording_id, stage, status, attempts, created_at, updated_at) "
            "VALUES (?,?,?,'queued',0,?,?)",
            (id, recording_id, stage, now, now),
        )
        return id

    @staticmethod
    def claim_next(conn: sqlite3.Connection) -> JobRow | None:
        r = conn.execute(
            "SELECT * FROM job WHERE status='queued' ORDER BY created_at LIMIT 1"
        ).fetchone()
        if not r:
            return None
        conn.execute(
            "UPDATE job SET status='running', attempts=attempts+1, updated_at=? WHERE id=?",
            (utcnow(), r["id"]),
        )
        r = conn.execute("SELECT * FROM job WHERE id=?", (r["id"],)).fetchone()
        return JobRow.from_row(r)

    @staticmethod
    def finish(conn: sqlite3.Connection, id: str, status: str, error: str | None = None) -> None:
        conn.execute(
            "UPDATE job SET status=?, error=?, updated_at=? WHERE id=?",
            (status, error, utcnow(), id),
        )

    @staticmethod
    def reset_running(conn: sqlite3.Connection) -> int:
        """On startup: jobs left 'running' by a crashed process go back to 'queued'."""
        cur = conn.execute(
            "UPDATE job SET status='queued', updated_at=? WHERE status='running'", (utcnow(),)
        )
        return int(cur.rowcount)

    @staticmethod
    def for_recording(conn: sqlite3.Connection, recording_id: str) -> list[JobRow]:
        rows = conn.execute(
            "SELECT * FROM job WHERE recording_id=? ORDER BY created_at DESC", (recording_id,)
        ).fetchall()
        return [JobRow.from_row(r) for r in rows]

    @staticmethod
    def has_active(conn: sqlite3.Connection, recording_id: str, stage: str) -> bool:
        r = conn.execute(
            "SELECT 1 FROM job WHERE recording_id=? AND stage=? AND status IN ('queued','running')",
            (recording_id, stage),
        ).fetchone()
        return r is not None


class EventRepo:
    @staticmethod
    def append(
        conn: sqlite3.Connection,
        type: str,
        payload: dict[str, Any],
        recording_id: str | None = None,
    ) -> str:
        id = uuid7()
        conn.execute(
            "INSERT INTO event (id, type, version, recording_id, payload_json, created_at) "
            "VALUES (?,?,1,?,?,?)",
            (id, type, recording_id, json.dumps(payload), utcnow()),
        )
        return id

    @staticmethod
    def for_recording(conn: sqlite3.Connection, recording_id: str) -> list[dict[str, Any]]:
        rows = conn.execute(
            "SELECT * FROM event WHERE recording_id=? ORDER BY created_at", (recording_id,)
        ).fetchall()
        return [
            {
                "event_id": r["id"],
                "type": r["type"],
                "version": r["version"],
                "recording_id": r["recording_id"],
                "occurred_at": r["created_at"],
                "payload": json.loads(r["payload_json"]),
            }
            for r in rows
        ]
