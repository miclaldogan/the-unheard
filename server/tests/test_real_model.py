"""Integration smoke test with the REAL CLAP model and real ESC-50 audio.

Skipped unless the weights are cached and ESC-50 clips are present under data/eval/esc50.
Run explicitly:  uv run pytest -m real_model tests/test_real_model.py -s
"""

from __future__ import annotations

import csv
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.conftest import make_settings, run_jobs
from unheard.app import create_app

ESC = Path(__file__).resolve().parents[1] / "data" / "eval" / "esc50"
HF = (
    Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface"))
    / "hub"
    / "models--laion--clap-htsat-unfused"
)

pytestmark = [
    pytest.mark.real_model,
    pytest.mark.skipif(
        not HF.exists(), reason="CLAP weights not cached (run `uv run unheard fetch-model`)"
    ),
    pytest.mark.skipif(not (ESC / "esc50.csv").exists(), reason="ESC-50 subset not downloaded"),
]


def clips(category: str, n: int) -> list[Path]:
    rows = [
        r
        for r in csv.DictReader(open(ESC / "esc50.csv"))
        if r["category"] == category and (ESC / r["filename"]).exists()
    ]
    # distinct source recordings (ESC-50 filename: fold-source-take-target)
    seen: set[str] = set()
    out: list[Path] = []
    for r in rows:
        src = r["filename"].split("-")[1]
        if src in seen:
            continue
        seen.add(src)
        out.append(ESC / r["filename"])
        if len(out) == n:
            break
    return out


def upload(c: TestClient, p: Path) -> str:
    with p.open("rb") as fh:
        r = c.post("/api/recordings", files={"file": (p.name, fh, "audio/wav")})
    assert r.status_code == 202, r.text
    return str(r.json()["recording_id"])


def test_real_clap_end_to_end_with_learning(tmp_path: Path) -> None:
    settings = make_settings(tmp_path, model_name="laion/clap-htsat-unfused")
    bells = clips("church_bells", 3)
    rain = clips("rain", 3)
    if len(bells) < 3 or len(rain) < 3:
        pytest.skip("need 3 distinct-source clips per class")
    with TestClient(create_app(settings, web_dist=Path("/nonexistent"))) as c:
        assert c.post("/api/model/load").json()["status"] == "ready"
        st = c.get("/api/model").json()
        assert st["embedding_dim"] == 512 and st["revision"] not in (None, "unknown")
        ids = {p: upload(c, p) for p in bells + rain}
        run_jobs(c)
        preds = {p: c.get(f"/api/recordings/{rid}/prediction").json() for p, rid in ids.items()}
        for p, pr in preds.items():
            assert pr["state"] == "awaiting_feedback", p.name
            assert pr["model"]["id"] == "laion/clap-htsat-unfused"
            assert pr["base"]["inference_ms"] < 5000
        # the ears alone recognise bells (strong class in the benchmark)
        top_bells = [preds[p]["base"]["candidates"][0]["slug"] for p in bells]
        print("\nbells base top-1:", top_bells)
        assert top_bells.count("church_bells") >= 2
        # functional learning demo: teach a *wrong-but-consistent* custom name on two rain clips
        held_out = rain[2]
        before = c.get(f"/api/recordings/{ids[held_out]}/prediction").json()["fused"]["candidates"]
        before_names = [x["name"] for x in before[:3]]
        for p in rain[:2]:
            r = c.post(
                f"/api/recordings/{ids[p]}/annotations", json={"new_labels": ["Roof gutter"]}
            )
            assert r.status_code == 201, r.text
        after = c.get(f"/api/recordings/{ids[held_out]}/prediction").json()["fused"]
        after_names = [x["name"] for x in after["candidates"][:3]]
        print(
            "held-out rain before:",
            before_names,
            "after:",
            after_names,
            "nearest exemplar cos:",
            round(after["novelty"]["nearest_exemplar_similarity"], 3),
        )
        gutter = next(x for x in after["candidates"] if x["name"] == "Roof gutter")
        assert gutter["n_exemplars"] == 2 and gutter["memory_similarity"] is not None
        assert gutter["rank"] <= 3  # memory pulls the taught name into the top hypotheses
        assert "Roof gutter" not in before_names
        # bells are unaffected by rain memory
        pb = c.get(f"/api/recordings/{ids[bells[0]]}/prediction").json()["fused"]
        assert pb["candidates"][0]["slug"] == "church_bells"
        nb = c.get(f"/api/recordings/{ids[held_out]}/neighbours").json()
        assert nb[0]["labels"] == ["Roof gutter"]
