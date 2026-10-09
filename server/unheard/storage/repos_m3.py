"""Repositories for visual artifacts and atlas state (M3)."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any

import numpy as np
from numpy.typing import NDArray

from unheard.storage.ids import uuid7
from unheard.storage.repos import utcnow


@dataclass(frozen=True)
class ArtifactRow:
    id: str
    recording_id: str
    generator_version: int
    seed: int
    dsp_version: int
    model_version_id: str | None
    geometry_hash: str
    params: dict[str, Any]
    status: str
    created_at: str
    updated_at: str

    @classmethod
    def from_row(cls, r: sqlite3.Row) -> ArtifactRow:
        return cls(
            r["id"],
            r["recording_id"],
            int(r["generator_version"]),
            int(r["seed"]),
            int(r["dsp_version"]),
            r["model_version_id"],
            r["geometry_hash"],
            json.loads(r["params_json"]),
            r["status"],
            r["created_at"],
            r["updated_at"],
        )


class ArtifactRepo:
    @staticmethod
    def upsert(
        conn: sqlite3.Connection,
        *,
        recording_id: str,
        generator_version: int,
        seed: int,
        dsp_version: int,
        model_version_id: str | None,
        geometry_hash: str,
        params: dict[str, Any],
    ) -> ArtifactRow:
        now = utcnow()
        existing = conn.execute(
            "SELECT id FROM visual_artifact WHERE recording_id=? AND generator_version=?",
            (recording_id, generator_version),
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE visual_artifact SET seed=?, dsp_version=?, model_version_id=?, geometry_hash=?, "
                "params_json=?, status='ready', updated_at=? WHERE id=?",
                (
                    seed,
                    dsp_version,
                    model_version_id,
                    geometry_hash,
                    json.dumps(params),
                    now,
                    existing["id"],
                ),
            )
            rid = str(existing["id"])
        else:
            rid = uuid7()
            conn.execute(
                "INSERT INTO visual_artifact (id, recording_id, generator_version, seed, dsp_version, "
                "model_version_id, geometry_hash, params_json, status, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,'ready',?,?)",
                (
                    rid,
                    recording_id,
                    generator_version,
                    seed,
                    dsp_version,
                    model_version_id,
                    geometry_hash,
                    json.dumps(params),
                    now,
                    now,
                ),
            )
        return ArtifactRepo.get_by_id(conn, rid)  # type: ignore[return-value]

    @staticmethod
    def get_by_id(conn: sqlite3.Connection, id: str) -> ArtifactRow | None:
        r = conn.execute("SELECT * FROM visual_artifact WHERE id=?", (id,)).fetchone()
        return ArtifactRow.from_row(r) if r else None

    @staticmethod
    def get(
        conn: sqlite3.Connection, recording_id: str, generator_version: int
    ) -> ArtifactRow | None:
        r = conn.execute(
            "SELECT * FROM visual_artifact WHERE recording_id=? AND generator_version=?",
            (recording_id, generator_version),
        ).fetchone()
        return ArtifactRow.from_row(r) if r else None

    @staticmethod
    def all(conn: sqlite3.Connection, generator_version: int) -> list[ArtifactRow]:
        rows = conn.execute(
            "SELECT a.* FROM visual_artifact a JOIN recording r ON r.id=a.recording_id "
            "WHERE a.generator_version=? AND r.deleted_at IS NULL ORDER BY a.created_at",
            (generator_version,),
        ).fetchall()
        return [ArtifactRow.from_row(r) for r in rows]

    @staticmethod
    def mark_stale(conn: sqlite3.Connection, recording_id: str) -> None:
        conn.execute(
            "UPDATE visual_artifact SET status='stale', updated_at=? WHERE recording_id=?",
            (utcnow(), recording_id),
        )


@dataclass
class AtlasStateRow:
    id: str
    model_version_id: str
    layout_version: int
    basis: NDArray[np.float32] | None  # (4, dim): components (2), mean, meta[scale, ev, n]
    basis_n: int
    explained_variance: float | None
    positions: dict[str, list[float]]
    atlas_version: int
    updated_at: str

    @classmethod
    def from_row(cls, r: sqlite3.Row) -> AtlasStateRow:
        basis = None
        if r["basis"]:
            flat = np.frombuffer(r["basis"], dtype="<f4")
            basis = flat.reshape(4, -1).astype(np.float32)
        return cls(
            r["id"],
            r["model_version_id"],
            int(r["layout_version"]),
            basis,
            int(r["basis_n"]),
            float(r["explained_variance"]) if r["explained_variance"] is not None else None,
            json.loads(r["positions_json"]),
            int(r["atlas_version"]),
            r["updated_at"],
        )


class AtlasStateRepo:
    @staticmethod
    def get(
        conn: sqlite3.Connection, model_version_id: str, layout_version: int
    ) -> AtlasStateRow | None:
        r = conn.execute(
            "SELECT * FROM atlas_state WHERE model_version_id=? AND layout_version=?",
            (model_version_id, layout_version),
        ).fetchone()
        return AtlasStateRow.from_row(r) if r else None

    @staticmethod
    def save(
        conn: sqlite3.Connection,
        *,
        model_version_id: str,
        layout_version: int,
        basis: NDArray[np.floating] | None,
        basis_n: int,
        explained_variance: float | None,
        positions: dict[str, list[float]],
        atlas_version: int,
    ) -> None:
        blob = np.asarray(basis, dtype="<f4").tobytes() if basis is not None else None
        existing = conn.execute(
            "SELECT id FROM atlas_state WHERE model_version_id=? AND layout_version=?",
            (model_version_id, layout_version),
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE atlas_state SET basis=?, basis_n=?, explained_variance=?, positions_json=?, "
                "atlas_version=?, updated_at=? WHERE id=?",
                (
                    blob,
                    basis_n,
                    explained_variance,
                    json.dumps(positions),
                    atlas_version,
                    utcnow(),
                    existing["id"],
                ),
            )
        else:
            conn.execute(
                "INSERT INTO atlas_state (id, model_version_id, layout_version, basis, basis_n, explained_variance, "
                "positions_json, atlas_version, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    uuid7(),
                    model_version_id,
                    layout_version,
                    blob,
                    basis_n,
                    explained_variance,
                    json.dumps(positions),
                    atlas_version,
                    utcnow(),
                ),
            )

    @staticmethod
    def delete(conn: sqlite3.Connection, model_version_id: str, layout_version: int) -> None:
        conn.execute(
            "DELETE FROM atlas_state WHERE model_version_id=? AND layout_version=?",
            (model_version_id, layout_version),
        )
