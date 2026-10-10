"""Composition service: validation, idempotent creation, background rendering, persistence."""

from __future__ import annotations

import hashlib
import io
import json
import logging
import threading
import traceback
from typing import Any

import numpy as np
import soundfile as sf

from unheard.dsp.features import DSP_VERSION
from unheard.errors import NotFound, NotReady, ValidationFailed
from unheard.events import (
    COMPOSITION_CREATED,
    COMPOSITION_DELETED,
    COMPOSITION_FAILED,
    COMPOSITION_PLANNED,
    COMPOSITION_RENDERED,
    COMPOSITION_REVISED,
)
from unheard.music import ANALYSIS_VERSION, COMPOSER_VERSION, PLANNER_VERSION, RENDER_VERSION
from unheard.music.engine import SourceInput, compose
from unheard.music.planner import DEFAULT_CONTROLS, MAX_SOURCES
from unheard.music.render import SR, to_pcm16
from unheard.music.roles import ROLES
from unheard.storage.blobs import BlobStore
from unheard.storage.db import Database
from unheard.storage.repos import AudioAssetRepo, EventRepo, FeatureSetRepo, RecordingRepo
from unheard.storage.repos_m4 import CompositionRepo, CompositionRow

log = logging.getLogger(__name__)

REQUIRED_ARRAYS = (
    "rms_envelope_db",
    "flatness",
    "centroid_hz",
    "flux",
    "onset_strength",
    "onset_times_s",
    "mel_times_s",
    "times_s",
)
MIN_DURATION_S, MAX_DURATION_S, DEFAULT_DURATION_S = 15.0, 90.0, 45.0
ALL_MODES = ("legacy", "organic", "composed")
DEFAULT_MODE = "composed"
LICENSE_NOTE = (
    "This composition contains transformed audio from your own recordings, which may include "
    "unintended background speech. It stays on this machine unless you export it."
)


def _wav_bytes(x: np.ndarray) -> bytes:
    buf = io.BytesIO()
    sf.write(buf, to_pcm16(x), SR, format="WAV", subtype="PCM_16")
    return buf.getvalue()


def _norm_controls(c: dict[str, float] | None) -> dict[str, float]:
    out = dict(DEFAULT_CONTROLS)
    for k, v in (c or {}).items():
        if k not in out:
            raise ValidationFailed(f"unknown control {k!r}; allowed: {sorted(out)}")
        out[k] = round(float(min(1.0, max(0.0, v))), 3)
    return out


class CompositionService:
    def __init__(self, db: Database, blobs: BlobStore, *, poll_s: float = 0.25) -> None:
        self.db = db
        self.blobs = blobs
        self.poll_s = poll_s
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        self._run_lock = threading.Lock()  # one render at a time (memory bound)

    # ------------------------------------------------------------------ lifecycle
    def start(self) -> None:
        with self.db.transaction() as conn:
            n = CompositionRepo.reset_processing(conn)
        if n:
            log.warning("re-queued %d interrupted composition renders", n)
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="composition-worker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                if not self.run_pending():
                    self._wake.wait(self.poll_s)
                    self._wake.clear()
            except Exception:  # pragma: no cover - defensive
                log.exception("composition worker error")
                self._stop.wait(1.0)

    def run_pending(self) -> int:
        """Render every queued composition synchronously; returns how many were processed."""
        n = 0
        while True:
            with self.db.connection() as conn:
                cid = CompositionRepo.next_queued(conn)
            if cid is None:
                return n
            self.process(cid)
            n += 1

    # ------------------------------------------------------------------ creation
    def create(
        self,
        recording_ids: list[str],
        *,
        seed: int | None = None,
        controls: dict[str, float] | None = None,
        duration_s: float | None = None,
        role_overrides: dict[str, str] | None = None,
        name: str | None = None,
        parent_id: str | None = None,
        mode: str = DEFAULT_MODE,
    ) -> tuple[CompositionRow, bool]:
        """Create (or return the existing identical) composition. Returns ``(row, created)``."""
        if mode not in ALL_MODES:
            raise ValidationFailed(f"mode must be one of {list(ALL_MODES)}")
        ids = list(dict.fromkeys(recording_ids))
        if not ids:
            raise ValidationFailed("select at least one recording")
        if len(ids) > MAX_SOURCES:
            raise ValidationFailed(f"at most {MAX_SOURCES} recordings per composition")
        dur = DEFAULT_DURATION_S if duration_s is None else float(duration_s)
        if not (MIN_DURATION_S <= dur <= MAX_DURATION_S):
            raise ValidationFailed(f"duration_s must be {MIN_DURATION_S:.0f}–{MAX_DURATION_S:.0f}")
        ctrl = _norm_controls(controls)
        overrides_in = role_overrides or {}
        for r in overrides_in.values():
            if r not in ROLES:
                raise ValidationFailed(f"unknown role {r!r}; allowed: {list(ROLES)}")

        sources: list[dict[str, str]] = []
        with self.db.connection() as conn:
            for rid in ids:
                rec = RecordingRepo.get(conn, rid)
                if rec is None:
                    raise NotFound(f"recording {rid} not found")
                if rec.status != "ready":
                    raise NotReady(f"recording {rid} is {rec.status}; wait until it is ready")
                if (
                    AudioAssetRepo.get(conn, rid, "canonical") is None
                    or FeatureSetRepo.latest(conn, rid) is None
                ):
                    raise NotReady(f"recording {rid} has no features yet")
                sources.append({"recording_id": rid, "content_hash": rec.content_hash})
        for rid in overrides_in:
            if rid not in ids:
                raise ValidationFailed(f"role override for unselected recording {rid}")
        sources.sort(key=lambda s: (s["content_hash"], s["recording_id"]))  # canonical order
        hashes = [s["content_hash"] for s in sources]
        if len(set(hashes)) != len(hashes):
            raise ValidationFailed("selection contains identical audio twice")
        if seed is None:
            seed = int.from_bytes(hashlib.sha256("|".join(hashes).encode()).digest()[:4], "big")
        by_rid = {s["recording_id"]: s["content_hash"] for s in sources}
        ov_hash = {by_rid[r]: v for r, v in overrides_in.items()}
        versions = {
            "planner": PLANNER_VERSION if mode == "legacy" else COMPOSER_VERSION,
            "render": RENDER_VERSION,
            "analysis": ANALYSIS_VERSION,
            "dsp": DSP_VERSION,
        }
        req = hashlib.sha256(
            json.dumps(
                {
                    "sources": hashes,
                    "seed": seed,
                    "controls": ctrl,
                    "duration": round(dur, 3),
                    "overrides": ov_hash,
                    "mode": mode,
                    "versions": versions,
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()
        with self.db.transaction() as conn:
            existing = CompositionRepo.by_request(conn, req)
            if existing is not None:
                return existing, False
            cid = CompositionRepo.insert(
                conn,
                parent_id=parent_id,
                name=(name or "Untitled orchestra")[:80],
                seed=int(seed),
                versions=versions,
                request_hash=req,
                controls=ctrl,
                overrides=ov_hash,
                target_duration_s=dur,
                sources=sources,
                mode=mode,
            )
            EventRepo.append(
                conn,
                COMPOSITION_REVISED if parent_id else COMPOSITION_CREATED,
                {
                    "composition_id": cid,
                    "parent_id": parent_id,
                    "seed": seed,
                    "sources": len(sources),
                },
            )
            row = CompositionRepo.get(conn, cid)
        self._wake.set()
        assert row is not None
        return row, True

    def variation(
        self, parent_id: str, *, seed: int | None = None, controls: dict[str, float] | None = None
    ) -> tuple[CompositionRow, bool]:
        with self.db.connection() as conn:
            parent = CompositionRepo.get(conn, parent_id)
            if parent is None:
                raise NotFound("composition not found")
            srcs = CompositionRepo.sources(conn, parent_id)
            live = [s["recording_id"] for s in srcs if RecordingRepo.get(conn, s["recording_id"])]
        if len(live) != len(srcs):
            raise NotReady("a source recording was deleted; this composition cannot be re-rendered")
        if seed is None:
            seed = int.from_bytes(
                hashlib.sha256(f"{parent.id}:{parent.seed}".encode()).digest()[:4], "big"
            )
        by_hash = {s["content_hash"]: s["recording_id"] for s in srcs}
        return self.create(
            live,
            seed=seed,
            controls={**parent.controls, **(controls or {})},
            duration_s=parent.target_duration_s,
            role_overrides={by_hash[h]: r for h, r in parent.overrides.items() if h in by_hash},
            name=parent.name,
            parent_id=parent.id,
            mode=parent.mode,
        )

    def retry(self, cid: str) -> CompositionRow:
        with self.db.transaction() as conn:
            row = CompositionRepo.get(conn, cid)
            if row is None:
                raise NotFound("composition not found")
            if row.status in ("queued", "processing"):
                raise NotReady("a render is already queued or running")
            if row.status == "ready":
                return row
            CompositionRepo.requeue(conn, cid)
            row = CompositionRepo.get(conn, cid)
        self._wake.set()
        assert row is not None
        return row

    # ------------------------------------------------------------------ rendering
    def _load_source(self, content_hash: str, recording_id: str) -> SourceInput:
        with self.db.connection() as conn:
            rec = RecordingRepo.get(conn, recording_id)
            if rec is None:
                raise NotFound(f"source recording {recording_id} was deleted")
            if rec.content_hash != content_hash:
                raise NotFound(f"source recording {recording_id} changed")
            asset = AudioAssetRepo.get(conn, recording_id, "canonical")
            fs = FeatureSetRepo.latest(conn, recording_id)
        if asset is None or fs is None:
            raise NotReady(f"recording {recording_id} lost its canonical audio or features")
        samples, sr = sf.read(self.blobs.absolute(asset.path), dtype="float64", always_2d=False)
        samples = np.asarray(samples, dtype=np.float64)
        if samples.ndim != 1:
            samples = samples.mean(axis=1)
        with np.load(self.blobs.absolute(fs.artifact_path)) as z:
            arrays = {k: np.asarray(z[k], dtype=np.float64) for k in REQUIRED_ARRAYS}
        return SourceInput(content_hash, samples, arrays, int(sr))

    def process(self, cid: str) -> None:
        with self._run_lock:
            with self.db.transaction() as conn:
                row = CompositionRepo.get(conn, cid)
                if row is None or row.status != "queued":
                    return
                CompositionRepo.set_processing(conn, cid)
                srcs = CompositionRepo.sources(conn, cid)
            try:
                self._render(row, srcs)
            except BaseException as e:  # noqa: BLE001 - recorded, never raised into the worker
                log.warning("composition %s failed: %s", cid, e)
                self.blobs.delete_composition_dir(cid)
                msg = e.args[0] if isinstance(e, NotFound | NotReady) and e.args else str(e)
                with self.db.transaction() as conn:
                    if CompositionRepo.get(conn, cid) is not None:
                        CompositionRepo.set_failed(conn, cid, f"{type(e).__name__}: {msg}")
                        EventRepo.append(
                            conn,
                            COMPOSITION_FAILED,
                            {
                                "composition_id": cid,
                                "error": str(msg)[:300],
                                "trace": traceback.format_exc(limit=3)[-600:],
                            },
                        )
                if isinstance(e, KeyboardInterrupt | SystemExit):
                    raise

    def _render(self, row: CompositionRow, srcs: list[dict[str, Any]]) -> None:
        cid = row.id
        inputs = [self._load_source(s["content_hash"], s["recording_id"]) for s in srcs]
        rid_by_hash = {s["content_hash"]: s["recording_id"] for s in srcs}
        res = compose(
            inputs,
            seed=row.seed,
            controls=row.controls,
            duration_s=row.target_duration_s,
            role_overrides=row.overrides,
            mode=row.mode,
        )
        plan = res.plan
        # files first (atomic each); the DB row flips to 'ready' only after all exist
        master_rel = self.blobs.composition_path(cid, "master.wav")
        master_bytes = _wav_bytes(res.master)
        self.blobs.write_atomic(master_rel, master_bytes)
        tracks_out = []
        for t in plan["tracks"]:
            data = _wav_bytes(res.stems[t["id"]])
            rel = self.blobs.composition_path(cid, f"stems/{t['id']}.wav")
            self.blobs.write_atomic(rel, data)
            tracks_out.append(
                {
                    "track_key": t["id"],
                    "recording_id": rid_by_hash[t["source"]],
                    "content_hash": t["source"],
                    "role": t["role"],
                    "layer_order": t["layer_order"],
                    "pan": t["pan"],
                    "enters": t["enters"],
                    "stem_path": rel,
                    "stem_sha256": hashlib.sha256(data).hexdigest(),
                }
            )
        events_out = []
        for e in plan["events"]:
            events_out.append(
                {
                    "seq": e["seq"],
                    "track_key": e["track"],
                    "recording_id": rid_by_hash[e["source"]],
                    "kind": e["kind"],
                    "role": e["role"],
                    "section": e["section"],
                    "comp_start_s": e["t"],
                    "comp_dur_s": e["dur"],
                    "source_start_s": e["source_start_s"],
                    "source_end_s": e["source_end_s"],
                    "params": {
                        k: v
                        for k, v in e.items()
                        if k
                        not in (
                            "seq",
                            "track",
                            "source",
                            "role",
                            "section",
                            "t",
                            "dur",
                            "kind",
                            "source_start_s",
                            "source_end_s",
                        )
                    },
                }
            )
        src_out = []
        for s in srcs:
            h = s["content_hash"]
            src_out.append(
                {
                    "content_hash": h,
                    "role": res.roles[h].primary,
                    "secondary_role": res.roles[h].secondary,
                    "decision": res.roles[h].to_json(),
                    "analysis": res.analyses[h].to_json(),
                }
            )
        provenance = {
            "composition_id": cid,
            "seed": row.seed,
            "controls": row.controls,
            "mode": row.mode,
            "versions": {
                "planner": PLANNER_VERSION if row.mode == "legacy" else COMPOSER_VERSION,
                "render": RENDER_VERSION,
                "analysis": ANALYSIS_VERSION,
                "dsp": DSP_VERSION,
            },
            "plan_hash": res.plan_hash,
            "sample_rate": SR,
            "sources": [{"recording_id": rid_by_hash[h], "content_hash": h} for h in rid_by_hash],
            "note": LICENSE_NOTE,
        }
        self.blobs.write_atomic(
            self.blobs.composition_path(cid, "plan.json"), json.dumps(plan, indent=1).encode()
        )
        self.blobs.write_atomic(
            self.blobs.composition_path(cid, "provenance.json"),
            json.dumps(provenance, indent=1).encode(),
        )
        with self.db.transaction() as conn:
            if CompositionRepo.get(conn, cid) is None:  # deleted while rendering
                self.blobs.delete_composition_dir(cid)
                return
            for rid in rid_by_hash.values():
                if RecordingRepo.get(conn, rid) is None:  # source deleted while rendering
                    raise NotFound(f"source recording {rid} was deleted during rendering")
            CompositionRepo.complete(
                conn,
                cid,
                plan=plan,
                plan_hash=res.plan_hash,
                metrics=res.metrics,
                master_path=master_rel,
                master_sha256=hashlib.sha256(master_bytes).hexdigest(),
                duration_s=float(res.metrics["duration_s"]),
                sources=src_out,
                tracks=tracks_out,
                events=events_out,
            )
            EventRepo.append(
                conn,
                COMPOSITION_PLANNED,
                {
                    "composition_id": cid,
                    "plan_hash": res.plan_hash,
                    "events": len(events_out),
                    "tempo_bpm": plan["tempo_bpm"],
                },
            )
            EventRepo.append(
                conn,
                COMPOSITION_RENDERED,
                {
                    "composition_id": cid,
                    "master_sha256": hashlib.sha256(master_bytes).hexdigest(),
                    "duration_s": res.metrics["duration_s"],
                },
            )

    # ------------------------------------------------------------------ queries / lifecycle
    def get(self, cid: str) -> CompositionRow:
        with self.db.connection() as conn:
            row = CompositionRepo.get(conn, cid)
        if row is None:
            raise NotFound("composition not found")
        return row

    def delete(self, cid: str, *, reason: str = "user") -> None:
        with self.db.transaction() as conn:
            if CompositionRepo.get(conn, cid) is None:
                raise NotFound("composition not found")
            CompositionRepo.delete(conn, cid)
            EventRepo.append(conn, COMPOSITION_DELETED, {"composition_id": cid, "reason": reason})
        self.blobs.delete_composition_dir(cid)

    def delete_for_recording(self, recording_id: str) -> list[str]:
        """Privacy cascade: a deleted recording takes every composition built from it along."""
        with self.db.connection() as conn:
            ids = CompositionRepo.ids_for_recording(conn, recording_id)
        for cid in ids:
            try:
                self.delete(cid, reason="source_deleted")
            except NotFound:
                pass
        return ids

    # ------------------------------------------------------------------ ECHO-0 conductor
    def echo_lines(
        self, row: CompositionRow, srcs: list[dict[str, Any]], names: dict[str, str]
    ) -> list[dict[str, Any]]:
        """Deterministic lines; each states the evidence that licenses it."""
        if row.status != "ready":
            return []
        lines: list[dict[str, Any]] = []
        with self.db.connection() as conn:
            ready = [c for c in CompositionRepo.all(conn) if c.status == "ready"]
        first = min(ready, key=lambda c: c.created_at).id == row.id if ready else False
        if first:
            lines.append(
                {
                    "text": "I have remembered these sounds separately.\nI wonder what happens when I hear them together.",
                    "tag": "imagination",
                    "evidence": {"first_composition": True},
                }
            )
        per: list[tuple[str, float, float]] = []
        for s in srcs:
            a = s.get("analysis") or {}
            if a.get("period_s") and a.get("periodicity", 0) >= 0.3:
                per.append((s["recording_id"], float(a["period_s"]), float(a["periodicity"])))
        for i in range(len(per)):
            for j in range(i + 1, len(per)):
                ratio = per[i][1] / per[j][1]
                folded = ratio
                while folded < 0.75:
                    folded *= 2
                while folded > 1.5:
                    folded /= 2
                if abs(folded - 1.0) <= 0.04:
                    a, b = names.get(per[i][0], "one sound"), names.get(per[j][0], "another")
                    lines.append(
                        {
                            "text": f"{a} and {b} keep nearly the same pulse.\nI had not noticed that they could be related.",
                            "tag": "measured",
                            "evidence": {
                                "periods_s": [round(per[i][1], 3), round(per[j][1], 3)],
                                "recordings": [per[i][0], per[j][0]],
                            },
                        }
                    )
        with self.db.connection() as conn:
            plan = CompositionRepo.plan(conn, row.id) or {}
        conv = plan.get("conversation") or []
        answered = any(e.get("variation") == "response" for e in plan.get("events", []))
        if conv and answered:
            rid_of = {s["content_hash"]: s["recording_id"] for s in srcs}
            a = names.get(rid_of.get(conv[0]["lead_source"], ""), "one sound")
            b = names.get(rid_of.get(conv[0]["responder_source"], ""), "another")
            lines.append(
                {
                    "text": f"{a} spoke first.\n{b} answered in the silence.",
                    "tag": "measured",
                    "evidence": {"conversation": conv[0]["evidence"], "mode": row.mode},
                }
            )
        roles = [s["role"] for s in srcs if s["role"]]
        if roles:
            n_rhythm = sum(r in ("percussion", "rhythmic_texture", "accent") for r in roles)
            n_atmo = sum(r in ("texture", "drone", "granular") for r in roles)
            n_tonal = sum(r == "tonal_motif" for r in roles)
            lines.append(
                {
                    "text": f"{n_rhythm} of your sounds became rhythm, {n_atmo} became air, {n_tonal} became melody.",
                    "tag": "measured",
                    "evidence": {"roles": roles},
                }
            )
        lines.append(
            {
                "text": "This is what your world sounds like through my memory.",
                "tag": "imagination",
                "evidence": {"composition_id": row.id, "plan_hash": row.plan_hash},
            }
        )
        return lines
