"""Actual-model QA journey. Use only a fresh disposable backend; creates records/compositions.

Local ESC-50 clips are never copied into Git or licensed for a public demo by this script.
Set UNHEARD_REVIEW_URL, UNHEARD_ESC50_DIR, UNHEARD_REVIEW_DIR and optional UNHEARD_REVIEW_TOKEN.
"""

import csv
import json
import os
import time
from pathlib import Path

import httpx

BASE = os.environ.get("UNHEARD_REVIEW_URL", "http://127.0.0.1:8010")
token = os.environ.get("UNHEARD_REVIEW_TOKEN")
c = httpx.Client(
    base_url=BASE,
    timeout=90,
    headers={"Authorization": f"Bearer {token}"} if token else {},
)
OUT = Path(os.environ.get("UNHEARD_REVIEW_DIR", "/tmp/unheard-m55-review"))
OUT.mkdir(parents=True, exist_ok=True)


def get(p):
    r = c.get(p)
    r.raise_for_status()
    return r.json()


def post(p, **kw):
    r = c.post(p, **kw)
    r.raise_for_status()
    return r.json()


def wait(p, pred, limit=90):
    start = time.monotonic()
    while time.monotonic() - start < limit:
        j = get(p)
        if pred(j):
            return j, (time.monotonic() - start) * 1000
        time.sleep(0.4)
    raise RuntimeError(f"timeout: {p} {j}")


assert get("/api/narrative/state")["counts"]["taught"] == 0, (
    "Use a fresh disposable profile with no taught sounds"
)
start = time.monotonic()
model = post("/api/model/load")
assert model["status"] == "ready" and model["device"] == "cpu", model
esc = Path(
    os.environ.get(
        "UNHEARD_ESC50_DIR",
        str(Path(__file__).resolve().parents[1] / "server/data/eval/esc50"),
    )
)
rows = list(csv.DictReader((esc / "esc50.csv").open()))
paths = []
for category in ["rain", "church_bells"]:
    seen = set()
    for r in rows:
        p = esc / r["filename"]
        source = r["filename"].split("-")[1]
        if r["category"] == category and p.exists() and source not in seen:
            seen.add(source)
            paths.append((category, p))
            if len(seen) == 3:
                break
assert len(paths) == 6
results = []
for category, p in paths:
    t = time.monotonic()
    with p.open("rb") as fh:
        rec = post("/api/recordings", files={"file": (p.name, fh, "audio/wav")})
    rid = rec["recording_id"]
    detail, ms = wait(f"/api/recordings/{rid}", lambda j: j["status"] == "ready")
    pred, ims = wait(
        f"/api/recordings/{rid}/prediction",
        lambda j: j["state"] in ["awaiting_feedback", "inference_failed"],
    )
    assert pred["state"] == "awaiting_feedback", pred
    assert pred["model"]["id"] == "laion/clap-htsat-unfused"
    assert get(f"/api/recordings/{rid}/visual")
    results.append(
        {
            "id": rid,
            "category": category,
            "file": p.name,
            "processing_ms": ms,
            "prediction_wait_ms": ims,
            "base": pred["base"],
            "fused": pred["fused"],
        }
    )
rain = [r for r in results if r["category"] == "rain"]
bells = [r for r in results if r["category"] == "church_bells"]
held = rain[2]["id"]
before = get(f"/api/recordings/{held}/prediction")["fused"]["candidates"]
for r in rain[:2]:
    post(f"/api/recordings/{r['id']}/annotations", json={"new_labels": ["Roof gutter"]})
after = get(f"/api/recordings/{held}/prediction")["fused"]["candidates"]
gutter = next(r for r in after if r["name"] == "Roof gutter")
assert gutter["n_exemplars"] == 2 and gutter["rank"] <= 3
assert "Roof gutter" not in [r["name"] for r in before[:3]]
for r in [rain[2], *bells]:
    post(
        f"/api/recordings/{r['id']}/annotations",
        json={"new_labels": ["Roof gutter" if r["category"] == "rain" else "Bells"]},
    )
missions = get("/api/narrative/missions")
activation = (
    post("/api/narrative/missions/" + missions["candidates"][0]["id"] + "/activate")
    if missions["candidates"]
    else None
)
comp = post(
    "/api/compositions",
    json={
        "recording_ids": [r["id"] for r in bells],
        "mode": "composed",
        "seed": 55,
        "duration_s": 24,
    },
)
cid = comp.get("composition_id", comp.get("id"))
render, render_ms = wait(
    "/api/compositions/" + cid, lambda j: j["status"] in ["ready", "failed"], 120
)
assert render["status"] == "ready", render
current = get("/api/narrative/current")
immediate = current["utterance"]
ready, narr_ms = wait(
    "/api/narrative/current",
    lambda j: j["utterance"]["generation"]["status"] != "pending",
    90,
)
state = get("/api/narrative/state")
assert state["ending_unlocked"] and state["phase"] == "remembered"
comment = get("/api/narrative/compositions/" + cid + "/commentary")
atlas = get("/api/atlas")
assert atlas
report = {
    "actual_clap": True,
    "device": model["device"],
    "model": model,
    "records": results,
    "learning": {
        "before": [r["name"] for r in before[:3]],
        "after": [r["name"] for r in after[:3]],
        "exemplar": gutter,
    },
    "mission": activation,
    "composition": {"id": cid, "render_ms": render_ms, "status": render["status"]},
    "immediate_narrative": immediate,
    "settled_narrative": ready,
    "generation_wait_ms": narr_ms,
    "state": state,
    "composition_commentary": comment,
    "model_status": get("/api/narrative/model-status"),
    "atlas_nodes": len(atlas.get("nodes", [])),
    "total_s": time.monotonic() - start,
    "audio_provenance": "existing local ESC-50 evaluation clips, not for publication",
}
(OUT / "real-model-journey.json").write_text(json.dumps(report, indent=2))
print(
    json.dumps(
        {
            "ending": state["ending_unlocked"],
            "records": len(results),
            "learning": report["learning"],
            "render_ms": render_ms,
            "gemma": report["model_status"]["stats"],
        },
        indent=2,
    )
)
