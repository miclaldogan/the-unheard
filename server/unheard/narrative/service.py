"""NarrativeService: ties state derivation, evidence, Gemma, validation, templates and missions together.

Event-driven and non-blocking: reading the narrative never waits for the model. A template line is stored immediately;
a single background worker asks Gemma (if enabled and reachable), validates the answer against the facts, and upgrades the
row; on any failure the template stays and the reason is recorded. Recording, hearing, teaching and composing never depend on
this module.
"""

from __future__ import annotations

import hashlib
import json
import logging
import queue
import sqlite3
import threading
import time
from collections import Counter
from typing import Any

import numpy as np

from unheard.config import Settings
from unheard.errors import AppError, NotFound
from unheard.narrative import CONTRACT_VERSION
from unheard.narrative.evidence import composition_moment, facts_for
from unheard.narrative.facts import FactSet
from unheard.narrative.gemma import (
    LINES_SCHEMA,
    PICKS_SCHEMA,
    GemmaBackend,
    GemmaError,
    OllamaBackend,
    mission_prompt,
    utterance_prompt,
)
from unheard.narrative.missions import (
    FALLBACK,
    MAX_ACTIVE,
    SAFETY,
    MissionContext,
    evaluate,
    generate_candidates,
    row_from_db,
)
from unheard.narrative.state import (
    Snapshot,
    available_actions,
    build_state,
    current_moment,
    derive_snapshot,
    milestones,
    utcnow,
)
from unheard.narrative.templates import template_lines
from unheard.narrative.validate import check_text, validate_lines
from unheard.storage.db import Database
from unheard.storage.ids import uuid7

log = logging.getLogger(__name__)
MAX_QUEUE = 8
AVAILABILITY_TTL_S = 8.0


class MissionNotFound(AppError):
    status = 404
    code = "NARRATIVE_MISSION_NOT_FOUND"


class MissionNotAvailable(AppError):
    status = 409
    code = "NARRATIVE_MISSION_NOT_AVAILABLE"


class TooManyActive(AppError):
    status = 409
    code = "NARRATIVE_TOO_MANY_ACTIVE"


class NarrativeService:
    def __init__(
        self,
        settings: Settings,
        db: Database,
        blobs: Any,
        *,
        models_enabled: Any = lambda: False,
        backend: GemmaBackend | None = None,
    ) -> None:
        self.settings = settings
        self.db = db
        self.blobs = blobs
        self._models_enabled = models_enabled
        self.backend: GemmaBackend = backend or OllamaBackend(
            settings.narrative_runtime_url,
            timeout_s=settings.narrative_timeout_s,
            keep_alive=settings.narrative_keep_alive,
            num_ctx=settings.narrative_num_ctx,
            max_tokens=settings.narrative_max_output_tokens,
            temperature=settings.narrative_temperature,
        )
        self._q: queue.Queue[tuple[str, str]] = queue.Queue()
        self._pending: set[str] = set()
        self._cv = threading.Condition()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._avail: tuple[float, list[str] | None, str | None] = (0.0, None, None)
        self._stats: Counter[str] = Counter()
        self._reasons: Counter[str] = Counter()
        self._latencies: list[float] = []
        self._cold_first: float | None = None
        self._generating = False
        self._analysis_cache: dict[str, Any] = {}

    # ------------------------------------------------------------------ lifecycle
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="narrative-worker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._q.put(("", ""))
        if self._thread:
            self._thread.join(timeout=3)

    def _loop(self) -> None:
        while not self._stop.is_set():
            kind, key = self._q.get()
            if not kind:
                continue
            try:
                self._run_job(kind, key)
            except Exception:  # pragma: no cover - defensive
                log.exception("narrative job failed")

    def run_pending(self) -> int:
        """Process queued generation jobs synchronously (tests, worker disabled)."""
        n = 0
        while True:
            try:
                kind, key = self._q.get_nowait()
            except queue.Empty:
                return n
            if kind:
                self._run_job(kind, key)
                n += 1

    # ------------------------------------------------------------------ settings and model status
    def _meta(self, conn: sqlite3.Connection, key: str, default: Any = None) -> Any:
        r = conn.execute("SELECT value_json FROM narrative_meta WHERE key=?", (key,)).fetchone()
        return json.loads(r[0]) if r else default

    def _set_meta(self, conn: sqlite3.Connection, key: str, value: Any) -> None:
        conn.execute(
            "INSERT INTO narrative_meta (key, value_json) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
            (key, json.dumps(value)),
        )

    def gemma_enabled(self) -> bool:
        with self.db.connection() as conn:
            return bool(self.settings.narrative_gemma and self._meta(conn, "gemma_enabled", True))

    def set_gemma_enabled(self, enabled: bool) -> None:
        with self.db.transaction() as conn:
            self._set_meta(conn, "gemma_enabled", bool(enabled))
        self._avail = (0.0, None, None)

    def _availability(self, force: bool = False) -> tuple[list[str] | None, str | None]:
        t, installed, err = self._avail
        if (
            not force
            and time.monotonic() - t < AVAILABILITY_TTL_S
            and (installed is not None or err)
        ):
            return installed, err
        try:
            installed, err = self.backend.installed(), None
        except GemmaError as e:
            installed, err = None, e.reason
        self._avail = (time.monotonic(), installed, err)
        return installed, err

    def select_model(self) -> str | None:
        installed, _ = self._availability()
        if not installed:
            return None
        if self.settings.narrative_model:
            return (
                self.settings.narrative_model
                if self.settings.narrative_model in installed
                else None
            )
        for pref in self.settings.narrative_model_preference:
            if pref in installed:
                return pref
        return None

    def _unavailable_reason(self) -> str | None:
        """Why a template must be used right now (None = Gemma may be tried)."""
        if not self.gemma_enabled():
            return "disabled"
        installed, err = self._availability()
        if installed is None:
            return "unavailable" if err in (None, "unavailable", "timeout", "http_error") else err
        if self.select_model() is None:
            return "no_model"
        return None

    def model_status(self) -> dict[str, Any]:
        enabled = self.gemma_enabled()
        installed, err = self._availability()
        model = self.select_model()
        if not enabled:
            status = "disabled"
        elif installed is None:
            status = "unavailable"
        elif model is None:
            status = "no_model"
        elif self._generating and self._cold_first is None:
            status = "loading"
        else:
            status = "ready"
        lat = sorted(self._latencies)
        req = self._stats["requests"]
        fb = self._stats["fallbacks"]

        def pct(p: float) -> float | None:
            return None if not lat else round(lat[min(len(lat) - 1, int(p * len(lat)))], 1)

        return {
            "contract_version": CONTRACT_VERSION,
            "runtime": "ollama",
            "base_url": self.settings.narrative_runtime_url,
            "enabled": enabled,
            "available": installed is not None and model is not None and enabled,
            "status": status,
            "model": model,
            "installed": [m for m in (installed or []) if m.startswith("gemma")],
            "license": "Gemma Terms of Use"
            if (model or "").startswith("gemma3")
            else ("Apache-2.0" if model else None),
            "limits": {
                "timeout_s": self.settings.narrative_timeout_s,
                "max_concurrent": 1,
                "max_output_tokens": self.settings.narrative_max_output_tokens,
            },
            "stats": {
                "requests": req,
                "valid": self._stats["valid"],
                "fallbacks": fb,
                "valid_rate": round(self._stats["valid"] / req, 3) if req else None,
                "fallback_rate": round(fb / req, 3) if req else None,
                "latency_ms": {
                    "cold_first": None if self._cold_first is None else round(self._cold_first, 1),
                    "p50": pct(0.5),
                    "p95": pct(0.95),
                },
                "fallback_reasons": dict(self._reasons),
            },
        }

    def _gemma_brief(self) -> dict[str, Any]:
        st = self.model_status()
        return {"status": st["status"], "model": st["model"], "enabled": st["enabled"]}

    # ------------------------------------------------------------------ snapshot
    def snapshot(self) -> Snapshot:
        with self.db.connection() as conn:
            return derive_snapshot(conn, model_enabled=bool(self._models_enabled()))

    def state(self) -> dict[str, Any]:
        snap = self.snapshot()
        st = build_state(snap, self._gemma_brief())
        st.pop("_qualifying_composition_id", None)
        return st

    # ------------------------------------------------------------------ utterances
    def _bump(self, conn: sqlite3.Connection) -> int:
        rev = int(self._meta(conn, "revision", 0)) + 1
        self._set_meta(conn, "revision", rev)
        return rev

    def _known_labels(self, snap: Snapshot) -> set[str]:
        return {n.lower() for n in snap.label_names.values() if n}

    def _public(self, row: sqlite3.Row) -> dict[str, Any]:
        facts = [
            {k: v for k, v in f.items() if k != "values"} for f in json.loads(row["facts_json"])
        ]
        return {
            "id": row["id"],
            "revision": int(row["revision"]),
            "moment": {
                "kind": row["moment_kind"],
                "key": row["moment_key"],
                "act": row["act"],
                "occurred_at": row["occurred_at"],
            },
            "lines": json.loads(row["lines_json"]),
            "facts": facts,
            "source": row["source"],
            "model": row["model"],
            "generation": {
                "status": row["status"],
                "latency_ms": row["latency_ms"],
                "attempts": int(row["attempts"]),
                "fallback_reason": row["fallback_reason"],
            },
            "created_at": row["created_at"],
        }

    def _ensure_utterance(self, snap: Snapshot, moment: dict[str, Any]) -> Any:
        with self.db.connection() as conn:
            fs = facts_for(conn, snap, moment)
        fhash = fs.facts_hash()
        lines = template_lines(moment["kind"], moment["key"], fs)
        reason = self._unavailable_reason()
        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT * FROM narrative_utterance WHERE moment_key=?", (moment["key"],)
            ).fetchone()
            if row is not None and row["facts_hash"] == fhash:
                return row
            status = "fallback" if reason else "pending"
            if status == "pending" and len(self._pending) >= MAX_QUEUE:
                status, reason = "fallback", "busy"
            rev = self._bump(conn)
            now = utcnow()
            common = (
                moment["kind"],
                moment["act"],
                moment["occurred_at"],
                fhash,
                json.dumps(fs.to_json(full=True)),
                json.dumps(lines),
                json.dumps(fs.recording_ids()),
                moment.get("composition_id"),
                "template",
                None,
                status,
                reason,
                None,
                0,
                rev,
            )
            if row is None:
                conn.execute(
                    "INSERT INTO narrative_utterance (id, moment_key, moment_kind, act, occurred_at, facts_hash, facts_json, lines_json,"
                    " recording_ids_json, composition_id, source, model, status, fallback_reason, latency_ms, attempts, revision,"
                    " created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    ("nar_" + uuid7().replace("-", "")[-16:], moment["key"], *common, now, now),
                )
            else:
                conn.execute(
                    "UPDATE narrative_utterance SET moment_kind=?, act=?, occurred_at=?, facts_hash=?, facts_json=?, lines_json=?,"
                    " recording_ids_json=?, composition_id=?, source=?, model=?, status=?, fallback_reason=?, latency_ms=?, attempts=?,"
                    " revision=?, updated_at=? WHERE moment_key=?",
                    (*common, now, moment["key"]),
                )
            row = conn.execute(
                "SELECT * FROM narrative_utterance WHERE moment_key=?", (moment["key"],)
            ).fetchone()
        if status == "pending":
            self._enqueue("utterance", moment["key"])
        elif reason:
            self._stats["requests"] += 1
            self._stats["fallbacks"] += 1
            self._reasons[reason] += 1
        return row

    def _enqueue(self, kind: str, key: str) -> None:
        tag = f"{kind}:{key}"
        with self._cv:
            if tag in self._pending:
                return
            self._pending.add(tag)
        self._q.put((kind, key))

    def _finish(self, kind: str, key: str) -> None:
        with self._cv:
            self._pending.discard(f"{kind}:{key}")
            self._cv.notify_all()

    def _wait(self, moment_key: str, wait_ms: int) -> Any:
        deadline = time.monotonic() + max(0, min(wait_ms, 8000)) / 1000
        while True:
            with self.db.connection() as conn:
                row = conn.execute(
                    "SELECT * FROM narrative_utterance WHERE moment_key=?", (moment_key,)
                ).fetchone()
            if row["status"] != "pending" or time.monotonic() >= deadline:
                return row
            with self._cv:
                self._cv.wait(timeout=min(0.25, max(0.0, deadline - time.monotonic())))

    def current(self, wait_ms: int = 0) -> dict[str, Any]:
        snap = self.snapshot()
        moment = current_moment(snap)
        row = self._ensure_utterance(snap, moment)
        if row["status"] == "pending" and wait_ms > 0:
            row = self._wait(moment["key"], wait_ms)
        return {
            "contract_version": CONTRACT_VERSION,
            "utterance": self._public(row),
            "available_actions": available_actions(snap),
        }

    def commentary(self, composition_id: str, wait_ms: int = 0) -> dict[str, Any]:
        snap = self.snapshot()
        moment = composition_moment(snap, composition_id)
        if moment is None:
            with self.db.connection() as conn:
                r = conn.execute(
                    "SELECT status FROM composition WHERE id=?", (composition_id,)
                ).fetchone()
            if r is None:
                raise NotFound("composition not found")
            from unheard.errors import NotReady

            raise NotReady(f"composition is {r['status']}")
        row = self._ensure_utterance(snap, moment)
        if row["status"] == "pending" and wait_ms > 0:
            row = self._wait(moment["key"], wait_ms)
        return {
            "contract_version": CONTRACT_VERSION,
            "utterance": self._public(row),
            "available_actions": available_actions(snap),
        }

    def _alive_rows(self, snap: Snapshot, rows: list[sqlite3.Row]) -> list[sqlite3.Row]:
        comp_ids = {c.id for c in snap.comps}
        out = []
        for r in rows:
            ids = json.loads(r["recording_ids_json"])
            if any(i not in snap.recs for i in ids):
                continue  # cites a deleted recording
            if r["composition_id"] and r["composition_id"] not in comp_ids:
                continue
            out.append(r)
        return out

    def echo(self, recording_id: str | None, limit: int) -> dict[str, Any]:
        snap = self.snapshot()
        with self.db.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM narrative_utterance ORDER BY occurred_at DESC, created_at DESC"
            ).fetchall()
        rows = self._alive_rows(snap, list(rows))
        if recording_id:
            rows = [r for r in rows if recording_id in json.loads(r["recording_ids_json"])]
        return {
            "contract_version": CONTRACT_VERSION,
            "utterances": [self._public(r) for r in rows[:limit]],
        }

    # ------------------------------------------------------------------ generation worker
    def _run_job(self, kind: str, key: str) -> None:
        try:
            if kind == "utterance":
                self._gen_utterance(key)
            elif kind == "missions":
                self._gen_missions(key)
        finally:
            self._finish(kind, key)

    def _record_fallback(self, reason: str) -> None:
        self._stats["requests"] += 1
        self._stats["fallbacks"] += 1
        self._reasons[reason] += 1

    def _call(self, model: str, system: str, user: str, schema: dict[str, Any], seed: int) -> Any:
        self._generating = True
        try:
            gen = self.backend.generate(model, system, user, schema, seed=seed)
        finally:
            self._generating = False
        if self._cold_first is None:
            self._cold_first = gen.latency_ms
        self._latencies.append(gen.latency_ms)
        return gen

    def _gen_utterance(self, key: str) -> None:
        with self.db.connection() as conn:
            row = conn.execute(
                "SELECT * FROM narrative_utterance WHERE moment_key=?", (key,)
            ).fetchone()
        if row is None or row["status"] != "pending":
            return
        fs = FactSet.from_json(json.loads(row["facts_json"]))
        snap = self.snapshot()
        known = self._known_labels(snap)
        reason = self._unavailable_reason()
        model = self.select_model()
        attempts, latency, hint = 0, None, None
        if reason is None and model is not None:
            seed = int(hashlib.sha256(key.encode()).hexdigest()[:6], 16)
            for attempt in (1, 2):
                attempts = attempt
                system, user = utterance_prompt(row["moment_kind"], row["act"], fs, retry_hint=hint)
                try:
                    gen = self._call(model, system, user, LINES_SCHEMA, seed + attempt)
                except GemmaError as e:
                    reason = (
                        e.reason
                        if e.reason in ("timeout", "unavailable", "no_model", "invalid_json")
                        else "unavailable"
                    )
                    if e.reason == "invalid_json" and attempt == 1:
                        hint = "not valid JSON"
                        continue
                    break
                latency = gen.latency_ms
                res = validate_lines(gen.data, fs, known)
                if res.ok:
                    self._finish_row(
                        key, res.lines, "gemma", model, "ready", None, latency, attempts
                    )
                    self._stats["requests"] += 1
                    self._stats["valid"] += 1
                    return
                reason = "invalid_output"
                hint = res.reasons[0].split(":")[0] if res.reasons else "invalid"
                log.info("gemma output rejected for %s: %s", row["moment_kind"], res.reasons[:3])
        reason = reason or "unavailable"
        self._record_fallback(reason)
        self._finish_row(
            key,
            json.loads(row["lines_json"]),
            "template",
            None,
            "fallback",
            reason,
            latency,
            attempts,
        )

    def _finish_row(
        self,
        key: str,
        lines: list[dict[str, Any]],
        source: str,
        model: str | None,
        status: str,
        reason: str | None,
        latency: float | None,
        attempts: int,
    ) -> None:
        with self.db.transaction() as conn:
            rev = self._bump(conn)
            conn.execute(
                "UPDATE narrative_utterance SET lines_json=?, source=?, model=?, status=?, fallback_reason=?, latency_ms=?, attempts=?,"
                " revision=?, updated_at=? WHERE moment_key=?",
                (
                    json.dumps(lines),
                    source,
                    model,
                    status,
                    reason,
                    latency,
                    attempts,
                    rev,
                    utcnow(),
                    key,
                ),
            )

    # ------------------------------------------------------------------ missions
    def _analysis(self, conn: sqlite3.Connection, rid: str) -> Any:
        import soundfile as sf

        from unheard.music.analysis import analyze_source
        from unheard.music.service import REQUIRED_ARRAYS
        from unheard.storage.repos import AudioAssetRepo, FeatureSetRepo, RecordingRepo

        rec = RecordingRepo.get(conn, rid)
        if rec is None:
            return None
        if rec.content_hash in self._analysis_cache:
            return self._analysis_cache[rec.content_hash]
        asset, fs = AudioAssetRepo.get(conn, rid, "canonical"), FeatureSetRepo.latest(conn, rid)
        if asset is None or fs is None:
            return None
        x, sr = sf.read(self.blobs.absolute(asset.path), dtype="float64", always_2d=False)
        x = np.asarray(x if x.ndim == 1 else x.mean(axis=1))
        with np.load(self.blobs.absolute(fs.artifact_path)) as z:
            arrays = {k: np.asarray(z[k], dtype=np.float64) for k in REQUIRED_ARRAYS}
        a = analyze_source(rec.content_hash, x, int(sr), arrays)
        if len(self._analysis_cache) > 64:
            self._analysis_cache.clear()
        self._analysis_cache[rec.content_hash] = a
        return a

    def _context(self, snap: Snapshot) -> MissionContext:
        def summary(rid: str) -> dict[str, Any] | None:
            with self.db.connection() as conn:
                r = conn.execute(
                    "SELECT summary_json FROM feature_set WHERE recording_id=? ORDER BY dsp_version DESC LIMIT 1",
                    (rid,),
                ).fetchone()
            return json.loads(r[0]) if r else None

        def onset(rid: str) -> float | None:
            s = summary(rid)
            return None if s is None else float(s.get("onset_density_per_s", 0.0))

        def voiced(rid: str) -> float | None:
            try:
                with self.db.connection() as conn:
                    a = self._analysis(conn, rid)
                return None if a is None else float(a.voiced_ratio)
            except Exception:  # noqa: BLE001 - a missing measurement just means "unknown"
                return None

        def centroid(rid: str) -> float | None:
            s = summary(rid)
            return (
                None
                if s is None
                else float((s.get("spectral_centroid_hz") or {}).get("median", 0.0)) or None
            )

        def max_cos(rid: str, baseline: list[str]) -> float | None:
            with self.db.connection() as conn:

                def vec(r: str) -> np.ndarray | None:
                    row = conn.execute(
                        "SELECT vec, model_version_id FROM embedding WHERE recording_id=? AND window_idx=-1 ORDER BY created_at DESC LIMIT 1",
                        (r,),
                    ).fetchone()
                    return (
                        None
                        if row is None
                        else np.frombuffer(row["vec"], dtype="<f4").astype(np.float64)
                    )

                v = vec(rid)
                bs = [
                    b
                    for b in (vec(b) for b in baseline)
                    if b is not None and v is not None and b.shape == v.shape
                ]
            if v is None or not bs:
                c0 = centroid(rid)
                cs = [c for c in (centroid(b) for b in baseline) if c]
                if c0 and cs:  # DSP fallback: far in log-frequency from every baseline sound
                    return 0.0 if min(abs(np.log2(c0 / c)) for c in cs) >= 1.0 else 1.0
                return None
            n = np.linalg.norm(v)
            return float(max(float(b @ v) / max(float(np.linalg.norm(b)) * n, 1e-12) for b in bs))

        return MissionContext(onset, voiced, max_cos, centroid, dict(snap.label_names))

    def _mission_public(
        self,
        c: dict[str, Any],
        status: str,
        row: dict[str, Any] | None,
        wording: dict[str, str],
        progress: dict[str, int] | None,
    ) -> dict[str, Any]:
        return {
            "id": c["id"],
            "type": c["type"],
            "title": c["title"],
            "objective": c["objective"],
            "reason": c["reason"],
            "evidence": c["evidence"],
            "completion": c["completion"],
            "safe_fallback": FALLBACK,
            "safety": SAFETY,
            "status": status,
            "wording": wording,
            "activated_at": row["activated_at"] if row else None,
            "completed_at": row["completed_at"] if row else None,
            "progress": progress,
        }

    def missions(self) -> dict[str, Any]:
        snap = self.snapshot()
        ctx = self._context(snap)
        with self.db.connection() as conn:
            rows = [
                row_from_db(r)
                for r in conn.execute(
                    "SELECT * FROM narrative_mission ORDER BY activated_at"
                ).fetchall()
            ]
        active, completed = [], []
        for r in rows:
            if r["status"] == "active":
                ev = evaluate(snap, ctx, r)
                if ev["status"] != "active":
                    with self.db.transaction() as conn:
                        conn.execute(
                            "UPDATE narrative_mission SET status=?, completed_at=?, completion_evidence_json=? WHERE id=?",
                            (ev["status"], ev["completed_at"], json.dumps(ev["evidence"]), r["id"]),
                        )
                    r["status"], r["completed_at"], r["completion_evidence"] = (
                        ev["status"],
                        ev["completed_at"],
                        ev["evidence"],
                    )
                r["progress"] = ev["progress"]
            if r["status"] == "active":
                active.append(r)
            elif r["status"] == "completed":
                completed.append(r)
        taken = {r["id"] for r in rows if r["status"] in ("active", "completed")}
        cands = [c for c in generate_candidates(snap, ctx) if c.id not in taken]
        # selection (Gemma may reorder and reword; it can only choose among these)
        order, wording, sel = self._selection(cands)
        cand_json = [
            self._mission_public(
                c.public(),
                "available",
                None,
                wording.get(c.id, {"text": c.objective, "source": "template"}),
                None,
            )
            for c in sorted(cands, key=lambda c: order.index(c.id) if c.id in order else 99)
        ]

        def stored(r: dict[str, Any]) -> dict[str, Any]:
            s = r["snapshot"]
            return self._mission_public(
                {**s, "id": r["id"], "type": r["type"]},
                r["status"],
                r,
                {"text": s["objective"], "source": "template"},
                r.get("progress"),
            )

        return {
            "contract_version": CONTRACT_VERSION,
            "max_active": MAX_ACTIVE,
            "active": [stored(r) for r in active],
            "candidates": cand_json,
            "completed": [stored(r) for r in completed],
            "selection": sel,
        }

    def _selection(
        self, cands: list[Any]
    ) -> tuple[list[str], dict[str, dict[str, str]], dict[str, Any]]:
        ids = [c.id for c in cands]
        base_order = list(ids)
        if not cands:
            return (
                [],
                {},
                {"source": "template", "model": None, "fallback_reason": None, "status": "ready"},
            )
        h = hashlib.sha256("|".join(sorted(ids)).encode()).hexdigest()[:12]
        with self.db.connection() as conn:
            cached = self._meta(conn, f"selection:{h}")
        if cached:
            return (
                cached["order"] or base_order,
                {k: v for k, v in cached["wording"].items()},
                {
                    "source": cached["source"],
                    "model": cached.get("model"),
                    "fallback_reason": cached.get("fallback_reason"),
                    "status": cached["status"],
                },
            )
        reason = self._unavailable_reason()
        if reason:
            return (
                base_order,
                {},
                {
                    "source": "template",
                    "model": None,
                    "fallback_reason": reason,
                    "status": "fallback",
                },
            )
        self._enqueue("missions", json.dumps({"hash": h, "cands": [c.public() for c in cands]}))
        return (
            base_order,
            {},
            {"source": "template", "model": None, "fallback_reason": None, "status": "pending"},
        )

    def _gen_missions(self, key: str) -> None:
        payload = json.loads(key)
        cands = payload["cands"]
        fs = FactSet()
        for c in cands:
            fs.add(c["reason"], "system")
        model = self.select_model()
        order, wording, reason, latency = (
            [c["id"] for c in cands],
            {},
            self._unavailable_reason(),
            None,
        )
        if reason is None and model is not None:
            try:
                system, user = mission_prompt(cands, fs)
                gen = self._call(model, system, user, PICKS_SCHEMA, 7)
                latency = gen.latency_ms
                picks = gen.data.get("picks") if isinstance(gen.data, dict) else None
                known = self._known_labels(self.snapshot())
                order2: list[str] = []
                words2: dict[str, dict[str, str]] = {}
                ok = isinstance(picks, list) and 1 <= len(picks) <= 3
                for p in picks if isinstance(picks, list) and ok else []:
                    idx = p.get("id", "") if isinstance(p, dict) else ""
                    if not (
                        isinstance(idx, str)
                        and idx.startswith("M")
                        and idx[1:].isdigit()
                        and 1 <= int(idx[1:]) <= len(cands)
                    ) or not isinstance(p.get("text"), str):
                        ok = False
                        break
                    cid = cands[int(idx[1:]) - 1]["id"]
                    own = FactSet()
                    own.add(cands[int(idx[1:]) - 1]["reason"], "system")
                    text = " ".join(p["text"].split())
                    labels = {
                        str(e.get("label", "")).lower()
                        for e in cands[int(idx[1:]) - 1]["evidence"]
                        if e.get("label")
                    }
                    own.facts[0].values["labels"] = sorted(labels)
                    own.facts[0].values["label"] = next(iter(sorted(labels)), None)
                    bad = check_text(text, own, ["F1"], known, mission=True)
                    # the invitation may repeat the candidate's own number words/labels but nothing else
                    if bad or cid in order2:
                        ok = False
                        break
                    order2.append(cid)
                    words2[cid] = {"text": text, "source": "gemma"}
                if ok:
                    order = order2 + [i for i in order if i not in order2]
                    wording = words2
                    self._stats["requests"] += 1
                    self._stats["valid"] += 1
                    self._store_selection(
                        payload["hash"], order, wording, "gemma", model, None, "ready"
                    )
                    return
                reason = "invalid_output"
            except GemmaError as e:
                reason = (
                    e.reason
                    if e.reason in ("timeout", "unavailable", "no_model", "invalid_json")
                    else "unavailable"
                )
        del latency
        self._record_fallback(reason or "unavailable")
        self._store_selection(
            payload["hash"], order, {}, "template", None, reason or "unavailable", "fallback"
        )

    def _store_selection(
        self,
        h: str,
        order: list[str],
        wording: dict[str, Any],
        source: str,
        model: str | None,
        reason: str | None,
        status: str,
    ) -> None:
        with self.db.transaction() as conn:
            self._set_meta(
                conn,
                f"selection:{h}",
                {
                    "order": order,
                    "wording": wording,
                    "source": source,
                    "model": model,
                    "fallback_reason": reason,
                    "status": status,
                },
            )
            self._bump(conn)

    def activate(self, mission_id: str) -> tuple[dict[str, Any], bool]:
        snap = self.snapshot()
        ctx = self._context(snap)
        with self.db.connection() as conn:
            existing = conn.execute(
                "SELECT * FROM narrative_mission WHERE id=?", (mission_id,)
            ).fetchone()
            n_active = conn.execute(
                "SELECT COUNT(*) FROM narrative_mission WHERE status='active'"
            ).fetchone()[0]
        if existing is not None:
            row = row_from_db(existing)
            if row["status"] == "active":
                return self._active_public(snap, ctx, row), False
            raise MissionNotAvailable(f"mission is {row['status']}")
        cand = next((c for c in generate_candidates(snap, ctx) if c.id == mission_id), None)
        if cand is None:
            raise MissionNotFound("no mission with that id")
        if n_active >= MAX_ACTIVE:
            raise TooManyActive(f"{MAX_ACTIVE} missions are already active")
        pub = cand.public()
        now = utcnow()
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT INTO narrative_mission (id, type, status, params_json, baseline_json, snapshot_json, activated_at) VALUES (?,?,?,?,?,?,?)",
                (
                    cand.id,
                    cand.type,
                    "active",
                    json.dumps(cand.params),
                    json.dumps({"recording_ids": sorted(snap.recs)}),
                    json.dumps(
                        {
                            k: pub[k]
                            for k in ("title", "objective", "reason", "evidence", "completion")
                        }
                    ),
                    now,
                ),
            )
            self._bump(conn)
            r = conn.execute("SELECT * FROM narrative_mission WHERE id=?", (cand.id,)).fetchone()
        return self._active_public(snap, ctx, row_from_db(r)), True

    def _active_public(
        self, snap: Snapshot, ctx: MissionContext, row: dict[str, Any]
    ) -> dict[str, Any]:
        ev = evaluate(snap, ctx, row)
        s = row["snapshot"]
        return self._mission_public(
            {**s, "id": row["id"], "type": row["type"]},
            "active",
            row,
            {"text": s["objective"], "source": "template"},
            ev["progress"],
        )

    # ------------------------------------------------------------------ timeline
    def timeline(self, limit: int, before: str | None) -> dict[str, Any]:
        snap = self.snapshot()
        entries: list[dict[str, Any]] = []
        titles = {m["id"]: m["title"] for m in milestones(snap)}
        for m in milestones(snap):
            if m["achieved"]:
                entries.append(
                    {
                        "id": f"tl_ms_{m['id']}",
                        "type": "milestone",
                        "at": m["achieved_at"],
                        "act": None,
                        "milestone": {"id": m["id"], "title": titles[m["id"]]},
                    }
                )
        flags_at = {"act_1": "first_hearing", "act_2": "third_teaching", "act_3": "ending_reached"}
        nxt = {"act_1": "act_2", "act_2": "act_3", "act_3": "ending"}
        ms = {m["id"]: m for m in milestones(snap)}
        for a, mid in flags_at.items():
            if ms[mid]["achieved"]:
                entries.append(
                    {
                        "id": f"tl_act_{a}",
                        "type": "act_change",
                        "at": ms[mid]["achieved_at"],
                        "act": nxt[a],
                        "act_change": {"from": a, "to": nxt[a]},
                    }
                )
        with self.db.connection() as conn:
            urows = conn.execute("SELECT * FROM narrative_utterance").fetchall()
            mrows = [
                row_from_db(r) for r in conn.execute("SELECT * FROM narrative_mission").fetchall()
            ]
        for r in self._alive_rows(snap, list(urows)):
            entries.append(
                {
                    "id": f"tl_{r['id']}",
                    "type": "utterance",
                    "at": r["occurred_at"],
                    "act": r["act"],
                    "utterance": self._public(r),
                }
            )
        for m in mrows:
            ms_ = {"id": m["id"], "type": m["type"], "title": m["snapshot"].get("title")}
            entries.append(
                {
                    "id": f"tl_ma_{m['id']}",
                    "type": "mission_activated",
                    "at": m["activated_at"],
                    "act": None,
                    "mission": ms_,
                }
            )
            if m["status"] == "completed" and m["completed_at"]:
                entries.append(
                    {
                        "id": f"tl_mc_{m['id']}",
                        "type": "mission_completed",
                        "at": m["completed_at"],
                        "act": None,
                        "mission": ms_,
                    }
                )
        entries.sort(key=lambda e: (e["at"], e["id"]), reverse=True)
        if before:
            entries = [e for e in entries if e["at"] < before]
        page = entries[:limit]
        return {
            "contract_version": CONTRACT_VERSION,
            "entries": page,
            "next_before": page[-1]["at"] if len(entries) > limit else None,
        }
