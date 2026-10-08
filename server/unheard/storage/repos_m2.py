"""Repositories for the M2 tables (inference, labels, annotations, memory)."""

from __future__ import annotations

import builtins
import json
import re
import sqlite3
import unicodedata
from dataclasses import dataclass
from typing import Any

import numpy as np
from numpy.typing import NDArray

from unheard.storage.ids import uuid7
from unheard.storage.repos import utcnow
from unheard.storage.vectors import from_blob, to_blob

# ----------------------------------------------------------------------------- model_version


@dataclass(frozen=True)
class ModelVersionRow:
    id: str
    name: str
    revision: str
    framework: str
    preprocessing_version: int
    embedding_dim: int
    input_sample_rate: int
    license_note: str | None

    @classmethod
    def from_row(cls, r: sqlite3.Row) -> ModelVersionRow:
        return cls(
            r["id"],
            r["name"],
            r["revision"],
            r["framework"],
            int(r["preprocessing_version"]),
            int(r["embedding_dim"]),
            int(r["input_sample_rate"]),
            r["license_note"],
        )


class ModelVersionRepo:
    @staticmethod
    def get_or_create(
        conn: sqlite3.Connection,
        *,
        name: str,
        revision: str,
        framework: str,
        preprocessing_version: int,
        embedding_dim: int,
        input_sample_rate: int,
        license_note: str | None,
    ) -> ModelVersionRow:
        r = conn.execute(
            "SELECT * FROM model_version WHERE name=? AND revision=? AND preprocessing_version=?",
            (name, revision, preprocessing_version),
        ).fetchone()
        if r:
            return ModelVersionRow.from_row(r)
        id = uuid7()
        conn.execute(
            "INSERT INTO model_version (id, name, revision, framework, preprocessing_version, "
            "embedding_dim, input_sample_rate, license_note, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                id,
                name,
                revision,
                framework,
                preprocessing_version,
                embedding_dim,
                input_sample_rate,
                license_note,
                utcnow(),
            ),
        )
        return ModelVersionRepo.get(conn, id)  # type: ignore[return-value]

    @staticmethod
    def get(conn: sqlite3.Connection, id: str) -> ModelVersionRow | None:
        r = conn.execute("SELECT * FROM model_version WHERE id=?", (id,)).fetchone()
        return ModelVersionRow.from_row(r) if r else None

    @staticmethod
    def list(conn: sqlite3.Connection) -> list[ModelVersionRow]:
        return [ModelVersionRow.from_row(r) for r in conn.execute("SELECT * FROM model_version")]


# --------------------------------------------------------------------------------- embedding


@dataclass(frozen=True)
class EmbeddingRow:
    id: str
    recording_id: str
    model_version_id: str
    window_idx: int
    window_start_s: float
    window_end_s: float
    vec: NDArray[np.float32]

    @classmethod
    def from_row(cls, r: sqlite3.Row) -> EmbeddingRow:
        return cls(
            r["id"],
            r["recording_id"],
            r["model_version_id"],
            int(r["window_idx"]),
            float(r["window_start_s"]),
            float(r["window_end_s"]),
            from_blob(r["vec"], int(r["dim"])),
        )


class EmbeddingRepo:
    @staticmethod
    def upsert(
        conn: sqlite3.Connection,
        *,
        recording_id: str,
        model_version_id: str,
        window_idx: int,
        start_s: float,
        end_s: float,
        vec: NDArray[np.floating],
    ) -> str:
        v = np.asarray(vec, dtype=np.float32)
        existing = conn.execute(
            "SELECT id FROM embedding WHERE recording_id=? AND model_version_id=? AND window_idx=?",
            (recording_id, model_version_id, window_idx),
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE embedding SET window_start_s=?, window_end_s=?, dim=?, vec=?, created_at=? WHERE id=?",
                (start_s, end_s, v.size, to_blob(v), utcnow(), existing["id"]),
            )
            return str(existing["id"])
        id = uuid7()
        conn.execute(
            "INSERT INTO embedding (id, recording_id, model_version_id, window_idx, window_start_s, "
            "window_end_s, dim, vec, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                id,
                recording_id,
                model_version_id,
                window_idx,
                start_s,
                end_s,
                v.size,
                to_blob(v),
                utcnow(),
            ),
        )
        return id

    @staticmethod
    def pooled(
        conn: sqlite3.Connection, recording_id: str, model_version_id: str
    ) -> EmbeddingRow | None:
        r = conn.execute(
            "SELECT * FROM embedding WHERE recording_id=? AND model_version_id=? AND window_idx=-1",
            (recording_id, model_version_id),
        ).fetchone()
        return EmbeddingRow.from_row(r) if r else None

    @staticmethod
    def windows(
        conn: sqlite3.Connection, recording_id: str, model_version_id: str
    ) -> list[EmbeddingRow]:
        rows = conn.execute(
            "SELECT * FROM embedding WHERE recording_id=? AND model_version_id=? AND window_idx>=0 "
            "ORDER BY window_idx",
            (recording_id, model_version_id),
        ).fetchall()
        return [EmbeddingRow.from_row(r) for r in rows]

    @staticmethod
    def all_pooled(conn: sqlite3.Connection, model_version_id: str) -> list[EmbeddingRow]:
        rows = conn.execute(
            "SELECT e.* FROM embedding e JOIN recording r ON r.id=e.recording_id "
            "WHERE e.model_version_id=? AND e.window_idx=-1 AND r.deleted_at IS NULL",
            (model_version_id,),
        ).fetchall()
        return [EmbeddingRow.from_row(r) for r in rows]


# ------------------------------------------------------------------------------------- label

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(name: str) -> str:
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    s = _SLUG_RE.sub("_", s).strip("_")
    return s[:48]


@dataclass(frozen=True)
class LabelRow:
    id: str
    slug: str
    name: str
    origin: str
    text_prompt: str | None
    text_vec: NDArray[np.float32] | None
    text_model_version_id: str | None
    merged_into: str | None
    hue_seed: int
    created_at: str

    @classmethod
    def from_row(cls, r: sqlite3.Row) -> LabelRow:
        return cls(
            r["id"],
            r["slug"],
            r["name"],
            r["origin"],
            r["text_prompt"],
            from_blob(r["text_vec"]) if r["text_vec"] else None,
            r["text_model_version_id"],
            r["merged_into"],
            int(r["hue_seed"]),
            r["created_at"],
        )


class LabelRepo:
    @staticmethod
    def get(conn: sqlite3.Connection, id: str) -> LabelRow | None:
        r = conn.execute("SELECT * FROM label WHERE id=?", (id,)).fetchone()
        return LabelRow.from_row(r) if r else None

    @staticmethod
    def by_slug(conn: sqlite3.Connection, slug: str) -> LabelRow | None:
        r = conn.execute("SELECT * FROM label WHERE slug=?", (slug,)).fetchone()
        return LabelRow.from_row(r) if r else None

    @staticmethod
    def list(conn: sqlite3.Connection, q: str | None = None) -> list[LabelRow]:
        if q:
            like = f"%{q.lower()}%"
            rows = conn.execute(
                "SELECT * FROM label WHERE merged_into IS NULL AND (lower(name) LIKE ? OR slug LIKE ?) "
                "ORDER BY origin DESC, name",
                (like, like),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM label WHERE merged_into IS NULL ORDER BY origin DESC, name"
            ).fetchall()
        return [LabelRow.from_row(r) for r in rows]

    @staticmethod
    def create(
        conn: sqlite3.Connection,
        *,
        name: str,
        origin: str,
        text_prompt: str | None,
        text_vec: NDArray[np.floating] | None = None,
        text_model_version_id: str | None = None,
        slug: str | None = None,
    ) -> LabelRow:
        slug = slug or slugify(name)
        if not slug:
            raise ValueError("label name produces an empty slug")
        id = uuid7()
        hue = int.from_bytes(slug.encode()[:4].ljust(4, b"\0"), "big") % 360
        conn.execute(
            "INSERT INTO label (id, slug, name, origin, text_prompt, text_vec, text_model_version_id, "
            "hue_seed, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                id,
                slug,
                name.strip(),
                origin,
                text_prompt,
                to_blob(text_vec) if text_vec is not None else None,
                text_model_version_id,
                hue,
                utcnow(),
            ),
        )
        return LabelRepo.get(conn, id)  # type: ignore[return-value]

    @staticmethod
    def set_text_vec(
        conn: sqlite3.Connection, id: str, vec: NDArray[np.floating], model_version_id: str
    ) -> None:
        conn.execute(
            "UPDATE label SET text_vec=?, text_model_version_id=? WHERE id=?",
            (to_blob(vec), model_version_id, id),
        )

    @staticmethod
    def with_text_vec(conn: sqlite3.Connection, model_version_id: str) -> builtins.list[LabelRow]:
        rows = conn.execute(
            "SELECT * FROM label WHERE merged_into IS NULL AND text_vec IS NOT NULL AND text_model_version_id=? "
            "ORDER BY created_at",
            (model_version_id,),
        ).fetchall()
        return [LabelRow.from_row(r) for r in rows]


# -------------------------------------------------------------------------------- prediction


@dataclass(frozen=True)
class PredictionRow:
    id: str
    recording_id: str
    model_version_id: str
    kind: str
    memory_version: int
    score_kind: str
    results: list[dict[str, Any]]
    windows: list[dict[str, Any]] | None
    novelty: dict[str, Any] | None
    inference_ms: float | None
    created_at: str

    @classmethod
    def from_row(cls, r: sqlite3.Row) -> PredictionRow:
        return cls(
            r["id"],
            r["recording_id"],
            r["model_version_id"],
            r["kind"],
            int(r["memory_version"]),
            r["score_kind"],
            json.loads(r["results_json"]),
            json.loads(r["windows_json"]) if r["windows_json"] else None,
            json.loads(r["novelty_json"]) if r["novelty_json"] else None,
            float(r["inference_ms"]) if r["inference_ms"] is not None else None,
            r["created_at"],
        )


class PredictionRepo:
    @staticmethod
    def insert(
        conn: sqlite3.Connection,
        *,
        recording_id: str,
        model_version_id: str,
        kind: str,
        memory_version: int,
        score_kind: str,
        results: list[dict[str, Any]],
        windows: list[dict[str, Any]] | None,
        novelty: dict[str, Any] | None,
        inference_ms: float | None,
    ) -> str:
        id = uuid7()
        conn.execute(
            "INSERT INTO prediction (id, recording_id, model_version_id, kind, memory_version, score_kind, "
            "results_json, windows_json, novelty_json, inference_ms, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                id,
                recording_id,
                model_version_id,
                kind,
                memory_version,
                score_kind,
                json.dumps(results),
                json.dumps(windows) if windows is not None else None,
                json.dumps(novelty) if novelty is not None else None,
                inference_ms,
                utcnow(),
            ),
        )
        return id

    @staticmethod
    def latest(conn: sqlite3.Connection, recording_id: str, kind: str) -> PredictionRow | None:
        r = conn.execute(
            "SELECT * FROM prediction WHERE recording_id=? AND kind=? ORDER BY created_at DESC, id DESC LIMIT 1",
            (recording_id, kind),
        ).fetchone()
        return PredictionRow.from_row(r) if r else None

    @staticmethod
    def delete_kind(conn: sqlite3.Connection, recording_id: str, kind: str) -> None:
        conn.execute("DELETE FROM prediction WHERE recording_id=? AND kind=?", (recording_id, kind))

    @staticmethod
    def recordings_with_fused(conn: sqlite3.Connection) -> list[str]:
        rows = conn.execute(
            "SELECT DISTINCT recording_id FROM prediction WHERE kind='fused'"
        ).fetchall()
        return [r[0] for r in rows]


# -------------------------------------------------------------------------------- annotation


@dataclass(frozen=True)
class AnnotationRow:
    id: str
    recording_id: str
    action: str
    status: str
    label_ids: list[str]
    rejected_label_ids: list[str]
    is_unknown: bool
    descriptors: list[str]
    environment: str | None
    mood: str | None
    note: str | None
    prediction_id: str | None
    superseded_by: str | None
    created_at: str

    @classmethod
    def from_row(cls, r: sqlite3.Row) -> AnnotationRow:
        return cls(
            r["id"],
            r["recording_id"],
            r["action"],
            r["status"],
            json.loads(r["label_ids_json"]),
            json.loads(r["rejected_label_ids_json"]),
            bool(r["is_unknown"]),
            json.loads(r["descriptors_json"]),
            r["environment"],
            r["mood"],
            r["note"],
            r["prediction_id"],
            r["superseded_by"],
            r["created_at"],
        )


class AnnotationRepo:
    @staticmethod
    def insert(
        conn: sqlite3.Connection,
        *,
        recording_id: str,
        action: str,
        label_ids: list[str],
        rejected_label_ids: list[str],
        is_unknown: bool,
        descriptors: list[str],
        environment: str | None,
        mood: str | None,
        note: str | None,
        prediction_id: str | None,
    ) -> str:
        id = uuid7()
        conn.execute(
            "INSERT INTO annotation (id, recording_id, action, status, label_ids_json, rejected_label_ids_json, "
            "is_unknown, descriptors_json, environment, mood, note, prediction_id, created_at) "
            "VALUES (?,?,?,'active',?,?,?,?,?,?,?,?,?)",
            (
                id,
                recording_id,
                action,
                json.dumps(label_ids),
                json.dumps(rejected_label_ids),
                int(is_unknown),
                json.dumps(descriptors),
                environment,
                mood,
                note,
                prediction_id,
                utcnow(),
            ),
        )
        return id

    @staticmethod
    def active(conn: sqlite3.Connection, recording_id: str) -> AnnotationRow | None:
        r = conn.execute(
            "SELECT * FROM annotation WHERE recording_id=? AND status='active' ORDER BY created_at DESC LIMIT 1",
            (recording_id,),
        ).fetchone()
        return AnnotationRow.from_row(r) if r else None

    @staticmethod
    def history(conn: sqlite3.Connection, recording_id: str) -> list[AnnotationRow]:
        rows = conn.execute(
            "SELECT * FROM annotation WHERE recording_id=? ORDER BY created_at DESC, id DESC",
            (recording_id,),
        ).fetchall()
        return [AnnotationRow.from_row(r) for r in rows]

    @staticmethod
    def supersede(conn: sqlite3.Connection, old_id: str, new_id: str) -> None:
        conn.execute(
            "UPDATE annotation SET status='superseded', superseded_by=? WHERE id=?",
            (new_id, old_id),
        )

    @staticmethod
    def count_active(conn: sqlite3.Connection) -> int:
        return int(
            conn.execute("SELECT COUNT(*) FROM annotation WHERE status='active'").fetchone()[0]
        )

    @staticmethod
    def active_for_all(conn: sqlite3.Connection) -> list[AnnotationRow]:
        rows = conn.execute(
            "SELECT a.* FROM annotation a JOIN recording r ON r.id=a.recording_id "
            "WHERE a.status='active' AND r.deleted_at IS NULL ORDER BY a.created_at DESC"
        ).fetchall()
        return [AnnotationRow.from_row(r) for r in rows]


# ---------------------------------------------------------------------------------- exemplar


@dataclass(frozen=True)
class ExemplarRow:
    id: str
    annotation_id: str
    embedding_id: str
    recording_id: str
    label_id: str
    weight: float
    status: str
    created_at: str
    vec: NDArray[np.float32]

    @classmethod
    def from_row(cls, r: sqlite3.Row) -> ExemplarRow:
        return cls(
            r["id"],
            r["annotation_id"],
            r["embedding_id"],
            r["recording_id"],
            r["label_id"],
            float(r["weight"]),
            r["status"],
            r["created_at"],
            from_blob(r["vec"], int(r["dim"])),
        )


class ExemplarRepo:
    @staticmethod
    def insert(
        conn: sqlite3.Connection,
        *,
        annotation_id: str,
        embedding_id: str,
        recording_id: str,
        label_id: str,
        weight: float = 1.0,
    ) -> str:
        id = uuid7()
        conn.execute(
            "INSERT INTO exemplar (id, annotation_id, embedding_id, recording_id, label_id, weight, status, created_at) "
            "VALUES (?,?,?,?,?,?,'active',?)",
            (id, annotation_id, embedding_id, recording_id, label_id, weight, utcnow()),
        )
        return id

    @staticmethod
    def retract_for_annotation(conn: sqlite3.Connection, annotation_id: str) -> int:
        cur = conn.execute(
            "UPDATE exemplar SET status='retracted' WHERE annotation_id=? AND status='active'",
            (annotation_id,),
        )
        return int(cur.rowcount)

    @staticmethod
    def active(
        conn: sqlite3.Connection, model_version_id: str, *, exclude_recording: str | None = None
    ) -> list[ExemplarRow]:
        sql = (
            "SELECT x.*, e.vec AS vec, e.dim AS dim FROM exemplar x "
            "JOIN embedding e ON e.id=x.embedding_id JOIN recording r ON r.id=x.recording_id "
            "WHERE x.status='active' AND e.model_version_id=? AND r.deleted_at IS NULL"
        )
        params: list[Any] = [model_version_id]
        if exclude_recording:
            sql += " AND x.recording_id<>?"
            params.append(exclude_recording)
        rows = conn.execute(sql + " ORDER BY x.created_at", params).fetchall()
        return [ExemplarRow.from_row(r) for r in rows]

    @staticmethod
    def counts_by_label(conn: sqlite3.Connection, model_version_id: str) -> dict[str, int]:
        rows = conn.execute(
            "SELECT x.label_id, COUNT(*) FROM exemplar x JOIN embedding e ON e.id=x.embedding_id "
            "JOIN recording r ON r.id=x.recording_id "
            "WHERE x.status='active' AND e.model_version_id=? AND r.deleted_at IS NULL GROUP BY x.label_id",
            (model_version_id,),
        ).fetchall()
        return {r[0]: int(r[1]) for r in rows}

    @staticmethod
    def for_label(
        conn: sqlite3.Connection, label_id: str, model_version_id: str
    ) -> list[ExemplarRow]:
        rows = conn.execute(
            "SELECT x.*, e.vec AS vec, e.dim AS dim FROM exemplar x JOIN embedding e ON e.id=x.embedding_id "
            "JOIN recording r ON r.id=x.recording_id "
            "WHERE x.status='active' AND x.label_id=? AND e.model_version_id=? AND r.deleted_at IS NULL "
            "ORDER BY x.created_at DESC",
            (label_id, model_version_id),
        ).fetchall()
        return [ExemplarRow.from_row(r) for r in rows]


# --------------------------------------------------------------------------------- prototype


class PrototypeRepo:
    @staticmethod
    def upsert(
        conn: sqlite3.Connection,
        *,
        label_id: str,
        model_version_id: str,
        vec: NDArray[np.floating],
        n_eff: float,
        sigma: float,
        memory_version: int,
    ) -> None:
        conn.execute(
            "INSERT INTO prototype (label_id, model_version_id, vec, n_eff, sigma, memory_version, updated_at) "
            "VALUES (?,?,?,?,?,?,?) ON CONFLICT(label_id, model_version_id) DO UPDATE SET vec=excluded.vec, "
            "n_eff=excluded.n_eff, sigma=excluded.sigma, memory_version=excluded.memory_version, updated_at=excluded.updated_at",
            (label_id, model_version_id, to_blob(vec), n_eff, sigma, memory_version, utcnow()),
        )

    @staticmethod
    def delete(conn: sqlite3.Connection, label_id: str, model_version_id: str) -> None:
        conn.execute(
            "DELETE FROM prototype WHERE label_id=? AND model_version_id=?",
            (label_id, model_version_id),
        )

    @staticmethod
    def all(
        conn: sqlite3.Connection, model_version_id: str
    ) -> dict[str, tuple[NDArray[np.float32], float, float]]:
        rows = conn.execute(
            "SELECT * FROM prototype WHERE model_version_id=?", (model_version_id,)
        ).fetchall()
        return {
            r["label_id"]: (from_blob(r["vec"]), float(r["n_eff"]), float(r["sigma"])) for r in rows
        }


class MemoryMetaRepo:
    @staticmethod
    def version(conn: sqlite3.Connection) -> int:
        r = conn.execute("SELECT value_json FROM memory_meta WHERE key='memory_version'").fetchone()
        return int(json.loads(r[0])) if r else 0

    @staticmethod
    def bump(conn: sqlite3.Connection) -> int:
        v = MemoryMetaRepo.version(conn) + 1
        conn.execute(
            "INSERT INTO memory_meta (key, value_json) VALUES ('memory_version', ?) "
            "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
            (json.dumps(v),),
        )
        return v
