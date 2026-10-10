"""Migrating a real M1 database (schema 1 with data) to schema 2 keeps recordings usable."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from tests.conftest import make_settings, run_jobs
from tests.fixtures import synth
from unheard.app import create_app
from unheard.storage import db as dbmod


def test_m1_database_upgrades_in_place(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    settings = make_settings(tmp_path)
    # 1. build an M1-only schema by hiding migration 0002
    real_iterdir = Path.iterdir
    monkeypatch.setattr(
        Path,
        "iterdir",
        lambda self: (
            p
            for p in real_iterdir(self)
            if not p.name.startswith(("0002", "0003", "0004", "0005", "0006"))
        ),
    )
    with TestClient(create_app(settings, web_dist=Path("/nonexistent"))) as c:
        rid = c.post(
            "/api/recordings",
            files={
                "file": ("a.wav", synth.wav_bytes(synth.sine(440, 48000, 3.0), 48000), "audio/wav")
            },
        ).json()["recording_id"]
        run_jobs(c)
        assert c.app.state.services.db.schema_version == 1  # type: ignore[attr-defined]
    monkeypatch.setattr(Path, "iterdir", real_iterdir)
    raw = sqlite3.connect(settings.db_path)
    assert raw.execute("PRAGMA user_version").fetchone()[0] == 1
    assert raw.execute("SELECT name FROM sqlite_master WHERE name='embedding'").fetchone() is None
    raw.close()
    # 2. reopen: migrations 0002 … 0006 apply, old recording still complete, no inference yet
    with TestClient(create_app(settings, web_dist=Path("/nonexistent"))) as c:
        assert c.app.state.services.db.schema_version == 6  # type: ignore[attr-defined]
        d = c.get(f"/api/recordings/{rid}").json()
        assert d["status"] == "ready" and d["features"] is not None
        assert c.get(f"/api/recordings/{rid}/features").status_code == 200
        p = c.get(f"/api/recordings/{rid}/prediction").json()
        assert (
            p["state"] == "model_disabled" and p["base"] is None
        )  # explicit: old recordings need /infer
        assert c.get("/api/memory").json()["memory_version"] == 0
        # M3: the old recording gets a specimen from its stored features, and an atlas node
        v = c.get(f"/api/recordings/{rid}/visual").json()
        assert v["generator_version"] == 1 and v["params"]["semantic"]["state"] == "uncertain"
        atlas = c.get("/api/atlas").json()
        assert atlas["counts"]["nodes"] == 1 and atlas["nodes"][0]["embedded"] is False
    assert dbmod.MIGRATIONS_DIR.joinpath("0002_inference_memory.sql").exists()
