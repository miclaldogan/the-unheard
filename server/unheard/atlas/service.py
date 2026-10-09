"""Atlas service: nodes from persisted artifacts + embeddings, sparse edges, stable layout."""

from __future__ import annotations

import logging
import sqlite3
from typing import Any

import numpy as np

from unheard.atlas.graph import Edge, build_edges
from unheard.atlas.layout import (
    FREEZE_AT,
    LAYOUT_VERSION,
    Basis,
    fit_basis,
    nudge,
    polar_seed_positions,
    project,
)
from unheard.events import ATLAS_UPDATED
from unheard.storage.db import Database
from unheard.storage.repos import EventRepo, RecordingRepo
from unheard.storage.repos_m2 import (
    AnnotationRepo,
    EmbeddingRepo,
    LabelRepo,
    ModelVersionRepo,
    PredictionRepo,
)
from unheard.storage.repos_m3 import ArtifactRepo, AtlasStateRepo
from unheard.visual.service import VisualService
from unheard.visual.signature import GENERATOR_VERSION

log = logging.getLogger(__name__)


class AtlasService:
    def __init__(self, db: Database, visual: VisualService) -> None:
        self.db = db
        self.visual = visual

    # -- model version used for the atlas ---------------------------------------
    @staticmethod
    def current_model_version(conn: sqlite3.Connection) -> str | None:
        r = conn.execute(
            "SELECT model_version_id, COUNT(*) c FROM embedding WHERE window_idx=-1 GROUP BY model_version_id "
            "ORDER BY c DESC, model_version_id DESC LIMIT 1"
        ).fetchone()
        return str(r[0]) if r else None

    # -- build ---------------------------------------------------------------------
    def build(self, *, rebuild: bool = False) -> dict[str, Any]:
        self.visual.refresh_all()
        with self.db.transaction() as conn:
            mvid = self.current_model_version(conn)
            recs = {r.id: r for r in RecordingRepo.list(conn, limit=10000, offset=0)}
            artifacts = {a.recording_id: a for a in ArtifactRepo.all(conn, GENERATOR_VERSION)}
            embs = {e.recording_id: e for e in EmbeddingRepo.all_pooled(conn, mvid)} if mvid else {}
            anns = {a.recording_id: a for a in AnnotationRepo.active_for_all(conn)}
            names = {lab.id: lab for lab in LabelRepo.list(conn)}
            # nodes = recordings with an artifact; embedded ones take part in similarity/layout
            node_ids = [rid for rid in recs if rid in artifacts]
            embedded = [rid for rid in node_ids if rid in embs]
            labels = {
                rid: list(anns[rid].label_ids)
                for rid in node_ids
                if rid in anns and not anns[rid].is_unknown
            }
            vecs = (
                np.stack([embs[rid].vec for rid in embedded])
                if embedded
                else np.zeros((0, 1), np.float32)
            )
            edges = build_edges(embedded, vecs, labels)
            positions, basis_info, atlas_version, moved = self._layout(
                conn, mvid, embedded, vecs, rebuild
            )
            # un-embedded nodes (no inference yet) sit on an outer ring, deterministic by id
            outer = [rid for rid in node_ids if rid not in positions]
            for i, rid in enumerate(sorted(outer)):
                ang = 2 * np.pi * (i + 0.5) / max(1, len(outer))
                positions[rid] = [
                    round(float(1.15 * np.cos(ang)), 4),
                    round(float(1.15 * np.sin(ang)), 4),
                ]
            nodes = []
            for rid in node_ids:
                a = artifacts[rid]
                sem = a.params.get("semantic", {})
                fused = PredictionRepo.latest(conn, rid, "fused")
                base = PredictionRepo.latest(conn, rid, "base")
                ann = anns.get(rid)
                r = recs[rid]
                nodes.append(
                    {
                        "recording_id": rid,
                        "artifact_id": a.id,
                        "x": positions[rid][0],
                        "y": positions[rid][1],
                        "embedded": rid in embs,
                        "state": sem.get("state"),
                        "resolution": sem.get("resolution"),
                        "label": sem.get("label"),
                        "hue": sem.get("hue"),
                        "label_ids": labels.get(rid, []),
                        "confirmed_labels": sem.get("confirmed_labels", []),
                        "is_unknown": bool(ann and ann.is_unknown),
                        "descriptors": sem.get("descriptors", []),
                        "environment": sem.get("environment"),
                        "mood": sem.get("mood"),
                        "ears_top": base.results[0]["name"] if base and base.results else None,
                        "fused_top": fused.results[0]["name"] if fused and fused.results else None,
                        "novel": bool(fused and fused.novelty and fused.novelty.get("novel")),
                        "captured_at": r.captured_at or r.created_at,
                        "duration_s": r.duration_s,
                        "glyph": {
                            k: a.params["geometry"][k]
                            for k in (
                                "sharpness",
                                "symmetry_order",
                                "jitter",
                                "fragmentation",
                                "scale",
                                "energy",
                            )
                        },
                        "ring": a.params["geometry"]["ring"][
                            ::4
                        ],  # 32-point outline for node glyphs
                        "seed": a.seed,
                    }
                )
            anchors = self._anchors(positions, labels, names)
            state = self._progression(nodes, edges, anchors)
            payload = {
                "atlas_version": atlas_version,
                "layout_version": LAYOUT_VERSION,
                "generator_version": GENERATOR_VERSION,
                "model_version_id": mvid,
                "model": None,
                "basis": basis_info,
                "nodes": nodes,
                "edges": [e.__dict__ for e in edges],
                "anchors": anchors,
                "state": state,
                "counts": {
                    "nodes": len(nodes),
                    "embedded": len(embedded),
                    "edges": len(edges),
                    "unknown": sum(1 for n in nodes if n["state"] == "unknown"),
                    "uncertain": sum(1 for n in nodes if n["state"] == "uncertain"),
                    "confirmed": sum(1 for n in nodes if n["state"] == "confirmed"),
                    "custom_labels": sum(1 for lab in names.values() if lab.origin == "user"),
                },
            }
            if mvid:
                mv = ModelVersionRepo.get(conn, mvid)
                payload["model"] = {"id": mv.name, "revision": mv.revision} if mv else None
            if moved or rebuild:
                EventRepo.append(
                    conn,
                    ATLAS_UPDATED,
                    {
                        "atlas_version": atlas_version,
                        "nodes": len(nodes),
                        "edges": len(edges),
                        "placed": moved,
                        "rebuild": rebuild,
                    },
                )
            return payload

    def _layout(
        self,
        conn: sqlite3.Connection,
        mvid: str | None,
        ids: list[str],
        vecs: np.ndarray,
        rebuild: bool,
    ) -> tuple[dict[str, list[float]], dict[str, Any] | None, int, list[str]]:
        if not mvid or not ids:
            return {}, None, 0, []
        st = AtlasStateRepo.get(conn, mvid, LAYOUT_VERSION)
        positions: dict[str, list[float]] = dict(st.positions) if st else {}
        positions = {k: v for k, v in positions.items() if k in ids}
        basis = Basis.from_array(st.basis) if st and st.basis is not None else None
        atlas_version = st.atlas_version if st else 0
        placed: list[str] = []
        n = len(ids)
        if n < 3:
            new = polar_seed_positions(ids)
            if new != positions:
                placed = [rid for rid in ids if positions.get(rid) != new[rid]]
                positions = new
            basis = None
        else:
            must_fit = (
                basis is None or rebuild or (n < FREEZE_AT and (st is None or st.basis_n != n))
            )
            if must_fit:
                basis = fit_basis(vecs)
                positions = {}
            assert basis is not None
            pinned = [tuple(positions[r]) for r in ids if r in positions]
            for i, rid in enumerate(ids):
                if rid in positions:
                    continue
                p = project(basis, vecs[i])
                p = nudge(p, pinned)  # type: ignore[arg-type]
                positions[rid] = [round(p[0], 4), round(p[1], 4)]
                pinned.append(p)
                placed.append(rid)
        if placed or rebuild or st is None:
            atlas_version += 1
            AtlasStateRepo.save(
                conn,
                model_version_id=mvid,
                layout_version=LAYOUT_VERSION,
                basis=basis.to_array() if basis else None,
                basis_n=basis.n if basis else 0,
                explained_variance=basis.explained_variance if basis else None,
                positions=positions,
                atlas_version=atlas_version,
            )
        info = (
            None
            if basis is None
            else {
                "fitted_on": basis.n,
                "frozen": basis.n >= FREEZE_AT,
                "explained_variance_2d": round(basis.explained_variance, 4),
            }
        )
        return positions, info, atlas_version, placed

    @staticmethod
    def _anchors(
        positions: dict[str, list[float]], labels: dict[str, list[str]], names: dict[str, Any]
    ) -> list[dict[str, Any]]:
        by: dict[str, list[list[float]]] = {}
        for rid, lids in labels.items():
            if rid not in positions:
                continue
            for lid in lids:
                by.setdefault(lid, []).append(positions[rid])
        out = []
        for lid, pts in by.items():
            lab = names.get(lid)
            if lab is None:
                continue
            arr = np.asarray(pts)
            out.append(
                {
                    "label_id": lid,
                    "name": lab.name,
                    "origin": lab.origin,
                    "hue": lab.hue_seed,
                    "x": round(float(arr[:, 0].mean()), 4),
                    "y": round(float(arr[:, 1].mean()), 4),
                    "n": len(pts),
                    "spread": round(
                        float(np.sqrt(((arr - arr.mean(axis=0)) ** 2).sum(axis=1)).mean()), 4
                    )
                    if len(pts) > 1
                    else 0.0,
                }
            )
        return sorted(out, key=lambda a: -a["n"])

    @staticmethod
    def _progression(
        nodes: list[dict[str, Any]], edges: list[Edge], anchors: list[dict[str, Any]]
    ) -> str:
        """Visual state driven by semantic/acoustic facts, not just counts."""
        if not nodes:
            return "empty"
        if any(a["origin"] == "user" and a["n"] >= 1 for a in anchors):
            return "new_concept"
        if any(a["n"] >= 2 for a in anchors):
            return "learned_categories"
        if edges:
            return "emerging_relationships"
        return "first_observation" if len(nodes) == 1 else "scattered"

    def narrative(self, conn: sqlite3.Connection, payload: dict[str, Any]) -> list[dict[str, Any]]:
        """ECHO-0 lines for the atlas, each backed by the payload or an event."""
        lines: list[dict[str, Any]] = []
        st = payload["state"]
        nodes = payload["nodes"]
        if st == "empty":
            lines.append(
                {
                    "template": "atlas_empty",
                    "text": "My world is silent. Bring me a sound.",
                    "tags": ["imagination"],
                    "event_ids": [],
                }
            )
            return lines
        if st == "first_observation":
            lines.append(
                {
                    "template": "atlas_first",
                    "text": "This is my first memory. It has a shape now.",
                    "tags": ["memory"],
                    "event_ids": [],
                }
            )
        last = conn.execute(
            "SELECT id, type, payload_json, recording_id FROM event WHERE type IN ('ArtifactRendered','AtlasUpdated','AcousticMemoryUpdated','RecordingDeleted') ORDER BY created_at DESC LIMIT 6"
        ).fetchall()
        for r in last:
            if r["type"] == "RecordingDeleted":
                lines.append(
                    {
                        "template": "atlas_forgotten",
                        "text": "A memory was removed. The others did not move.",
                        "tags": ["memory"],
                        "event_ids": [r["id"]],
                    }
                )
                break
        strong = [e for e in payload["edges"] if e["type"] == "acoustic" and e["weight"] >= 0.75]
        if strong:
            e = max(strong, key=lambda x: x["weight"])
            lines.append(
                {
                    "template": "atlas_connected",
                    "text": f"These two memories appear connected (cosine {e['weight']:.2f}). I had not noticed their similarity before.",
                    "tags": ["model"],
                    "event_ids": [],
                    "edge": [e["a"], e["b"]],
                }
            )
        unk = [n for n in nodes if n["state"] == "unknown"]
        if unk:
            lines.append(
                {
                    "template": "atlas_unknown",
                    "text": f"{len(unk)} memor{'y' if len(unk) == 1 else 'ies'} still ha{'s' if len(unk) == 1 else 've'} no name. {'It' if len(unk) == 1 else 'They'} drift at the edge.",
                    "tags": ["memory"],
                    "event_ids": [],
                }
            )
        user_anchor = [a for a in payload["anchors"] if a["origin"] == "user"]
        if user_anchor:
            a = user_anchor[0]
            lines.append(
                {
                    "template": "atlas_new_concept",
                    "text": f"'{a['name']}' is a word you gave me. It now has a place in my world.",
                    "tags": ["memory"],
                    "event_ids": [],
                }
            )
        return lines
