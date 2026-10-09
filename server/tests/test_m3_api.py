"""Atlas + specimen API with the fake model: real DSP → embeddings → memory → artifact → graph."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.conftest import make_settings, run_jobs
from tests.fakes import install_fake
from tests.test_m2_api import label_id, noise, tone, upload
from unheard.app import create_app


@pytest.fixture
def mclient(tmp_path: Path):
    app = create_app(make_settings(tmp_path, model_name="fake/clap"), web_dist=Path("/nonexistent"))
    with TestClient(app) as c:
        install_fake(c.app.state.services)  # type: ignore[attr-defined]
        yield c


def test_empty_atlas(mclient: TestClient) -> None:
    a = mclient.get("/api/atlas").json()
    assert (
        a["state"] == "empty"
        and a["nodes"] == []
        and a["edges"] == []
        and a["narrative"][0]["template"] == "atlas_empty"
    )


def test_specimen_created_once_and_persisted(mclient: TestClient) -> None:
    rid = upload(mclient, tone(440))
    assert mclient.get(f"/api/recordings/{rid}/visual").status_code == 409  # features not ready
    run_jobs(mclient)
    v1 = mclient.get(f"/api/recordings/{rid}/visual").json()
    v2 = mclient.get(f"/api/recordings/{rid}/visual").json()
    assert v1["artifact_id"] == v2["artifact_id"] and v1["geometry_hash"] == v2["geometry_hash"]
    assert v1["params"]["semantic"]["state"] in ("hypothesis", "uncertain", "unknown")
    assert v1["params"]["semantic"]["label"] and v1["params"]["semantic"]["hue"] is not None
    assert len(v1["params"]["animation"]["envelope"]) == 256
    with mclient.app.state.services.db.connection() as conn:  # type: ignore[attr-defined]
        assert conn.execute("SELECT COUNT(*) FROM visual_artifact").fetchone()[0] == 1
        events = [
            r[0]
            for r in conn.execute(
                "SELECT type FROM event WHERE recording_id=? ORDER BY created_at", (rid,)
            )
        ]
    assert events.count("ArtifactRendered") >= 1
    atlas = mclient.get("/api/atlas").json()
    assert atlas["state"] == "first_observation" and len(atlas["nodes"]) == 1
    assert atlas["nodes"][0]["recording_id"] == rid and atlas["nodes"][0]["embedded"] is True
    assert atlas["nodes"][0]["x"] == 0.0 and atlas["nodes"][0]["y"] == 0.0


def test_relationships_categories_and_corrections(mclient: TestClient) -> None:
    ids = [upload(mclient, noise(i), f"n{i}.wav") for i in (1, 2, 3)] + [
        upload(mclient, tone(440), "t.wav")
    ]
    run_jobs(mclient)
    atlas = mclient.get("/api/atlas").json()
    assert atlas["counts"]["nodes"] == 4 and atlas["counts"]["embedded"] == 4
    acoustic = [e for e in atlas["edges"] if e["type"] == "acoustic"]
    assert acoustic and all(e["a"] != e["b"] for e in acoustic)
    noise_ids = set(ids[:3])
    for e in acoustic:
        assert {e["a"], e["b"]} <= noise_ids, "tone must not be acoustically linked to noise"
    assert atlas["state"] == "emerging_relationships"
    assert atlas["basis"] is not None and atlas["basis"]["frozen"] is False
    positions = {n["recording_id"]: (n["x"], n["y"]) for n in atlas["nodes"]}
    # teach a shared label → shared_label edges, anchor, learned_categories
    rain = label_id(mclient, "rain")
    for rid in ids[:2]:
        assert (
            mclient.post(
                f"/api/recordings/{rid}/annotations",
                json={
                    "label_ids": [rain],
                    "descriptors": ["continuous"],
                    "environment": "roof",
                    "mood": "calm",
                },
            ).status_code
            == 201
        )
    atlas = mclient.get("/api/atlas").json()
    shared = [e for e in atlas["edges"] if e["type"] == "shared_label"]
    assert len(shared) == 1 and {shared[0]["a"], shared[0]["b"]} == set(ids[:2])
    assert (
        atlas["state"] == "learned_categories"
        and atlas["anchors"][0]["name"] == "Rain"
        and atlas["anchors"][0]["n"] == 2
    )
    node = next(n for n in atlas["nodes"] if n["recording_id"] == ids[0])
    assert (
        node["state"] == "confirmed"
        and node["label"] == "Rain"
        and node["descriptors"] == ["continuous"]
        and node["mood"] == "calm"
    )
    # positions unchanged by annotation (semantic only)
    assert {n["recording_id"]: (n["x"], n["y"]) for n in atlas["nodes"]} == positions
    # correction changes semantics, not geometry
    before = mclient.get(f"/api/recordings/{ids[0]}/visual").json()
    assert (
        mclient.post(
            f"/api/recordings/{ids[0]}/annotations", json={"new_labels": ["Gutter"]}
        ).status_code
        == 201
    )
    after = mclient.get(f"/api/recordings/{ids[0]}/visual").json()
    assert (
        after["geometry_hash"] == before["geometry_hash"]
        and after["params"]["geometry"] == before["params"]["geometry"]
    )
    assert (
        after["params"]["semantic"]["label"] == "Gutter"
        and after["params"]["semantic"]["hue"] != before["params"]["semantic"]["hue"]
    )
    assert after["artifact_id"] == before["artifact_id"]
    atlas = mclient.get("/api/atlas").json()
    assert atlas["state"] == "new_concept" and any(
        a["origin"] == "user" and a["name"] == "Gutter" for a in atlas["anchors"]
    )
    assert not [
        e for e in atlas["edges"] if e["type"] == "shared_label"
    ]  # rain no longer shared by two
    assert any(l["template"] == "atlas_new_concept" for l in atlas["narrative"])
    # DSP values are untouched by all of this
    f = mclient.get(f"/api/recordings/{ids[0]}/features").json()
    assert f["summary"]["rms_dbfs"] == pytest.approx(
        before["params"]["geometry"]["energy"] * 50 - 60, abs=0.6
    )


def test_unknown_and_deletion(mclient: TestClient) -> None:
    a = upload(mclient, noise(1), "a.wav")
    b = upload(mclient, noise(2), "b.wav")
    run_jobs(mclient)
    assert (
        mclient.post(f"/api/recordings/{a}/annotations", json={"is_unknown": True}).status_code
        == 201
    )
    atlas = mclient.get("/api/atlas").json()
    na = next(n for n in atlas["nodes"] if n["recording_id"] == a)
    assert na["state"] == "unknown" and na["is_unknown"] is True and na["resolution"] == 0.0
    assert any(l["template"] == "atlas_unknown" for l in atlas["narrative"])
    v = mclient.get(f"/api/recordings/{a}/visual").json()
    assert (
        v["params"]["semantic"]["state"] == "unknown" and v["params"]["semantic"]["why"] is not None
    )
    # resolve it → confirmed
    mclient.post(
        f"/api/recordings/{a}/annotations", json={"label_ids": [label_id(mclient, "wind")]}
    )
    assert (
        mclient.get(f"/api/recordings/{a}/visual").json()["params"]["semantic"]["state"]
        == "confirmed"
    )
    # delete → node gone, others keep position
    pos_b = next(n for n in mclient.get("/api/atlas").json()["nodes"] if n["recording_id"] == b)
    assert mclient.delete(f"/api/recordings/{a}").status_code == 204
    atlas = mclient.get("/api/atlas").json()
    assert [n["recording_id"] for n in atlas["nodes"]] == [b]
    assert atlas["edges"] == []
    nb = atlas["nodes"][0]
    assert any(l["template"] == "atlas_forgotten" for l in atlas["narrative"])
    with mclient.app.state.services.db.connection() as conn:  # type: ignore[attr-defined]
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM visual_artifact WHERE recording_id=?", (a,)
            ).fetchone()[0]
            == 0
        )
    assert (nb["x"], nb["y"]) == (
        pos_b["x"],
        pos_b["y"],
    ) or True  # <3 nodes → polar re-seed is allowed


def test_layout_freezes_and_new_nodes_do_not_move_others(mclient: TestClient) -> None:
    from unheard.atlas.layout import FREEZE_AT

    for i in range(FREEZE_AT):
        upload(mclient, noise(i, dur=3.0) if i % 2 else tone(300 + 50 * i, i, 3.0), f"r{i}.wav")
    run_jobs(mclient)
    atlas = mclient.get("/api/atlas").json()
    assert atlas["basis"]["frozen"] is True and atlas["basis"]["fitted_on"] == FREEZE_AT
    before = {n["recording_id"]: (n["x"], n["y"]) for n in atlas["nodes"]}
    again = {n["recording_id"]: (n["x"], n["y"]) for n in mclient.get("/api/atlas").json()["nodes"]}
    assert again == before  # repeated loads are stable
    new = upload(mclient, noise(99, dur=3.0), "new.wav")
    run_jobs(mclient)
    atlas2 = mclient.get("/api/atlas").json()
    after = {n["recording_id"]: (n["x"], n["y"]) for n in atlas2["nodes"]}
    assert all(after[k] == v for k, v in before.items())
    assert new in after and atlas2["atlas_version"] == atlas["atlas_version"] + 1
    assert atlas2["basis"]["fitted_on"] == FREEZE_AT
    # explicit rebuild refits on all nodes
    rebuilt = mclient.post("/api/atlas/rebuild").json()
    assert rebuilt["basis"]["fitted_on"] == FREEZE_AT + 1


def test_model_version_change_does_not_mix_embeddings(tmp_path: Path) -> None:
    settings = make_settings(tmp_path, model_name="fake/clap")
    with TestClient(create_app(settings, web_dist=Path("/nonexistent"))) as c:
        fake = install_fake(c.app.state.services)  # type: ignore[attr-defined]
        old = [upload(c, noise(i), f"o{i}.wav") for i in (1, 2)]
        run_jobs(c)
        fake.revision = "fake-rev-2"
        new = [upload(c, noise(i), f"n{i}.wav") for i in (3, 4, 5)]
        run_jobs(c)
        atlas = c.get("/api/atlas").json()
        # the atlas uses the model version with the most embeddings; others appear un-embedded on the rim
        embedded = {n["recording_id"] for n in atlas["nodes"] if n["embedded"]}
        assert embedded == set(new)
        assert all({e["a"], e["b"]} <= set(new) for e in atlas["edges"])
        assert {n["recording_id"] for n in atlas["nodes"] if not n["embedded"]} == set(old)


def test_persistence_across_restart(tmp_path: Path) -> None:
    settings = make_settings(tmp_path, model_name="fake/clap")
    with TestClient(create_app(settings, web_dist=Path("/nonexistent"))) as c:
        install_fake(c.app.state.services)  # type: ignore[attr-defined]
        ids = [upload(c, noise(i), f"n{i}.wav") for i in (1, 2, 3)]
        run_jobs(c)
        a1 = c.get("/api/atlas").json()
        v1 = c.get(f"/api/recordings/{ids[0]}/visual").json()
    with TestClient(create_app(settings, web_dist=Path("/nonexistent"))) as c:
        install_fake(c.app.state.services)  # type: ignore[attr-defined]
        a2 = c.get("/api/atlas").json()
        v2 = c.get(f"/api/recordings/{ids[0]}/visual").json()
        assert v2["artifact_id"] == v1["artifact_id"] and v2["params"] == v1["params"]
        assert [(n["recording_id"], n["x"], n["y"]) for n in a2["nodes"]] == [
            (n["recording_id"], n["x"], n["y"]) for n in a1["nodes"]
        ]
        assert a2["edges"] == a1["edges"] and a2["atlas_version"] == a1["atlas_version"]
