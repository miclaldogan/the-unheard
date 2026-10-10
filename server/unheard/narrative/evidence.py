"""Evidence packets: the minimal facts the narrator may use for a moment (still layer 1: built from the database).

User-controlled strings (label names, descriptors) pass through ``sanitize_text`` and are only ever placed in fact
statements inside single quotes. Environment, mood and free-text notes are deliberately never included.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from unheard.narrative.facts import FactSet, Ref, band, sanitize_text
from unheard.narrative.state import ACT_TARGET_TEACH, Ann, Snapshot, current_act


def label_name(snap: Snapshot, label_id: str | None) -> str | None:
    if not label_id:
        return None
    return sanitize_text(snap.label_names.get(label_id)) or None


def _names(snap: Snapshot, ids: list[str]) -> list[str]:
    return [n for n in (label_name(snap, i) for i in ids) if n]


def _pred(conn: sqlite3.Connection, recording_id: str, kind: str) -> sqlite3.Row | None:
    row: sqlite3.Row | None = conn.execute(
        "SELECT * FROM prediction WHERE recording_id=? AND kind=? ORDER BY created_at DESC LIMIT 1",
        (recording_id, kind),
    ).fetchone()
    return row


def _top(results: list[dict[str, Any]]) -> tuple[str | None, float | None, float | None]:
    """(label_id, probability-like score or None, margin to the runner-up or None)"""
    if not results:
        return None, None, None
    top = results[0]
    score = top.get("fused_score")
    second = results[1] if len(results) > 1 else None
    if score is not None:
        fm = float(score) - float(second.get("fused_score", 0.0)) if second else float(score)
        return top.get("label_id"), float(score), fm
    sim = top.get("similarity")
    sim_margin = (
        (float(sim) - float(second.get("similarity", 0.0)))
        if (second and sim is not None)
        else None
    )
    return top.get("label_id"), None, sim_margin


def _confidence_word(score: float | None, margin: float | None) -> str:
    if score is not None:
        return band(score)
    if margin is None:
        return "unknown"
    return "high" if margin >= 0.08 else "moderate" if margin >= 0.03 else "low"


def _ann_facts(fs: FactSet, snap: Snapshot, a: Ann) -> None:
    names = _names(snap, a.label_ids)
    quoted = ", ".join(f"'{n}'" for n in names)
    verb = {
        "confirm": "confirmed",
        "correct": "corrected the ears to",
        "create": "gave a new name",
        "unknown": "could not name",
    }[a.action]
    fs.add(
        f"The player {verb} {quoted} for this recording."
        if names
        else "The player could not name this recording.",
        "user_confirmed",
        Ref("annotation", a.id, names[0] if names else None, "user_confirmed"),
        labels=names,
        label=names[0] if names else None,
        recording_ids=[a.recording_id],
    )
    desc = [sanitize_text(d, 24) for d in a.descriptors[:3] if sanitize_text(d, 24)]
    if desc:
        fs.add(
            "The player said it sounds " + ", ".join(f"'{d}'" for d in desc) + ".",
            "user_confirmed",
            Ref("annotation", a.id, None, "user_confirmed"),
            labels=desc,
        )


def facts_for(conn: sqlite3.Connection, snap: Snapshot, moment: dict[str, Any]) -> FactSet:
    fs = FactSet()
    kind = moment["kind"]
    n_taught, n_rec = len(snap.taught), len(snap.recs)
    if kind == "awaiting_sound":
        fs.add("No recording has been processed yet.", "system")
        return fs
    if kind in ("first_sound", "teaching", "correction", "unknown", "relationship"):
        rid = moment.get("recording_id")
        rec = snap.recs.get(rid) if rid else None
        if rec is not None:
            fs.add(
                f"The recording is {rec.duration_s:.0f} seconds long.",
                "measurement",
                Ref("recording", rec.id, None, "measurement"),
                recording_ids=[rec.id],
            )
    if kind == "first_sound":
        base = _pred(conn, moment["recording_id"], "base")
        fused = _pred(conn, moment["recording_id"], "fused")
        if base is not None:
            row = fused or base
            lid, score, margin = _top(json.loads(row["results_json"]))
            name = label_name(snap, lid)
            nov = (
                json.loads(fused["novelty_json"])
                if fused is not None and fused["novelty_json"]
                else {}
            )
            if name:
                fs.add(
                    f"The ears' strongest hypothesis is '{name}' (confidence {_confidence_word(score, margin)}). It is a hypothesis, not a fact.",
                    "model",
                    Ref("prediction", row["id"], name, "model"),
                    label=name,
                    recording_ids=[moment["recording_id"]],
                )
            if nov.get("novel"):
                fs.add(
                    "Nothing in memory is close and the ears are undecided.",
                    "model",
                    Ref("prediction", row["id"], None, "model"),
                )
        else:
            fs.add("The signal was recorded but the ears have not analysed it.", "system")
        fs.add(f"{n_rec} recording(s) have been processed so far.", "system")
    elif kind in ("teaching", "correction"):
        a = snap.active[moment["recording_id"]]
        _ann_facts(fs, snap, a)
        if a.label_ids and not a.is_unknown:
            has_exemplar = conn.execute(
                "SELECT 1 FROM exemplar WHERE annotation_id=? AND status='active' LIMIT 1", (a.id,)
            ).fetchone()
            if not has_exemplar:
                fs.add(
                    "The name is stored, but the ears have not analysed this recording yet, so memory is not updated.",
                    "system",
                    Ref("annotation", a.id, None, "system"),
                )
        if kind == "correction":
            # the annotation's link to the prediction it saw is cleared when memory re-scores; the ears' own (base)
            # hypothesis persists, so it is the truthful "before"
            p = None
            if a.prediction_id:
                p = conn.execute(
                    "SELECT * FROM prediction WHERE id=?", (a.prediction_id,)
                ).fetchone()
            if p is None:
                p = _pred(conn, a.recording_id, "base")
            if p is not None:
                lid, _s, _m = _top(json.loads(p["results_json"]))
                frm = label_name(snap, lid)
                if frm and frm.lower() not in {n.lower() for n in _names(snap, a.label_ids)}:
                    fs.add(
                        f"Before the correction the ears said '{frm}'.",
                        "model",
                        Ref("prediction", p["id"], frm, "model"),
                        label=frm,
                    )
        fs.add(
            f"{n_taught} of the player's recordings are taught so far; {ACT_TARGET_TEACH} are needed to compose.",
            "system",
        )
    elif kind == "unknown":
        rid = moment["recording_id"]
        ua = snap.active.get(rid)
        fz = snap.latest_fused.get(rid)
        if ua is not None and ua.is_unknown:
            fs.add(
                "The player could not name this recording either.",
                "user_confirmed",
                Ref("annotation", ua.id, None, "user_confirmed"),
            )
        nov = (fz or {}).get("novelty") or {}
        sim = nov.get("nearest_exemplar_similarity")
        if nov.get("novel") or sim is not None:
            txt = "ECHO-0 has no remembered sound close to this one"
            txt += f" (closest similarity {float(sim):.2f})." if sim is not None else "."
            fs.add(
                txt,
                "personal_memory",
                Ref("prediction", (fz or {}).get("id", rid), None, "personal_memory"),
            )
        fs.add("It remains unresolved.", "system")
    elif kind == "relationship":
        rid = moment["recording_id"]
        fr = snap.latest_fused[rid]
        nov = fr["novelty"] or {}
        mem = label_name(snap, nov.get("memory_top"))
        sim = nov.get("nearest_exemplar_similarity")
        if mem and sim is not None:
            fs.add(
                f"This recording resembles sounds the player taught as '{mem}' (similarity {float(sim):.2f}).",
                "personal_memory",
                Ref("prediction", fr["id"], mem, "personal_memory"),
                label=mem,
                recording_ids=[rid],
            )
        else:
            fs.add(
                "This recording resembles something in memory.",
                "personal_memory",
                Ref("prediction", fr["id"], None, "personal_memory"),
            )
    elif kind == "ready_to_compose":
        names = sorted({n for a in snap.taught for n in _names(snap, a.label_ids)})
        fs.add(f"{n_taught} recordings are taught.", "system")
        if names:
            fs.add(
                "The taught names are " + ", ".join(f"'{n}'" for n in names[:5]) + ".",
                "user_confirmed",
                labels=names[:5],
            )
        fs.add("No composition has been made from them yet.", "system")
    elif kind in ("composition", "ending"):
        _composition_facts(conn, snap, fs, moment["composition_id"])
        if kind == "ending":
            names = sorted({n for a in snap.taught for n in _names(snap, a.label_ids)})
            fs.add(f"The player taught {n_taught} recordings.", "system")
            if names:
                fs.add(
                    "Their names included " + ", ".join(f"'{n}'" for n in names[:5]) + ".",
                    "user_confirmed",
                    labels=names[:5],
                )
    return fs


def _composition_facts(conn: sqlite3.Connection, snap: Snapshot, fs: FactSet, comp_id: str) -> None:
    row = conn.execute("SELECT * FROM composition WHERE id=?", (comp_id,)).fetchone()
    if row is None or not row["plan_json"]:
        fs.add("A composition exists.", "system", Ref("composition", comp_id, None, "system"))
        return
    plan = json.loads(row["plan_json"])
    srcs = conn.execute(
        "SELECT * FROM composition_source WHERE composition_id=? ORDER BY position", (comp_id,)
    ).fetchall()
    by_hash = {s["content_hash"]: s for s in srcs}

    def name_of(content_hash: str | None) -> str | None:
        s = by_hash.get(content_hash or "")
        if s is None:
            return None
        a = snap.active.get(s["recording_id"])
        names = _names(snap, a.label_ids) if a and not a.is_unknown else []
        return names[0] if names else None

    rec_ids = [s["recording_id"] for s in srcs]
    fs.add(
        f"The composition uses {len(srcs)} of the player's recordings.",
        "measurement",
        Ref("composition", comp_id, None, "measurement"),
        recording_ids=rec_ids,
    )
    fs.add(
        f"It is in {row['mode']} mode, about {float(plan.get('tempo_bpm', 0)):.0f} beats per minute, {float(plan.get('duration_s', 0)):.0f} seconds long.",
        "measurement",
        Ref("composition", comp_id, None, "measurement"),
    )
    hier = plan.get("hierarchy") or {}
    roles = {
        "lead": "carries the lead",
        "foundation": "keeps the groove",
        "gesture": "marks the section changes",
    }
    for key, text in roles.items():
        nm = name_of(hier.get(key))
        if nm:
            fs.add(
                f"'{nm}' {text}.",
                "measurement",
                Ref("composition", comp_id, nm, "measurement"),
                label=nm,
            )
    beds = [n for n in (name_of(b) for b in hier.get("beds", [])) if n]
    if beds:
        fs.add(
            "The atmosphere comes from " + " and ".join(f"'{n}'" for n in beds) + ".",
            "measurement",
            Ref("composition", comp_id, beds[0], "measurement"),
            labels=beds,
        )
    for conv in (plan.get("conversation") or [])[:1]:
        a, b = name_of(conv.get("lead_source")), name_of(conv.get("responder_source"))
        sc = (conv.get("evidence") or {}).get("score")
        if a and b and sc is not None:
            fs.add(
                f"'{b}' answers '{a}' in the silence between its notes (fit {float(sc):.2f}).",
                "measurement",
                Ref("composition", comp_id, b, "measurement"),
                labels=[a, b],
            )
    ops = sorted({m["relation"]["operator"] for m in plan.get("motifs", []) if m.get("relation")})
    if ops:
        fs.add(
            "The lead idea comes back transformed: " + ", ".join(ops) + ".",
            "measurement",
            Ref("composition", comp_id, None, "measurement"),
        )
    if plan.get("key") is None:
        fs.add(
            "No source was pitched enough to give the piece a key.",
            "measurement",
            Ref("composition", comp_id, None, "measurement"),
        )


def composition_moment(snap: Snapshot, comp_id: str) -> dict[str, Any] | None:
    """The moment for an explicit composition (commentary endpoint)."""
    comp = next((c for c in snap.comps if c.id == comp_id), None)
    if comp is None:
        return None
    from unheard.narrative.state import qualifying_composition

    q = qualifying_composition(snap)
    act, _ = current_act(snap)
    kind = "ending" if (q is not None and q.id == comp_id and act == "ending") else "composition"
    return {
        "kind": kind,
        "key": f"{kind}:{comp_id}",
        "act": "ending" if kind == "ending" else "act_3",
        "occurred_at": comp.rendered_at or comp.created_at,
        "composition_id": comp_id,
    }
