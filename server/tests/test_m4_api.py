"""M4 composition API: create → render → persist → provenance → export → delete."""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from collections.abc import Iterator
from pathlib import Path

import pytest
import soundfile as sf
from fastapi.testclient import TestClient

from tests.conftest import make_settings, run_jobs
from tests.fixtures import synth
from tests.music_helpers import SR, steady_noise, tone_melody
from unheard.app import create_app


def _up(c: TestClient, x) -> str:  # type: ignore[no-untyped-def]
    r = c.post("/api/recordings", files={"file": ("c.wav", synth.wav_bytes(x, SR), "audio/wav")})
    assert r.status_code == 202, r.text
    return str(r.json()["recording_id"])


def _services(c: TestClient):  # type: ignore[no-untyped-def]
    return c.app.state.services  # type: ignore[attr-defined]


@pytest.fixture
def mc(tmp_path: Path) -> Iterator[TestClient]:
    app = create_app(make_settings(tmp_path), web_dist=Path("/nonexistent"))
    with TestClient(app) as c:
        yield c


@pytest.fixture
def ids(mc: TestClient) -> list[str]:
    out = [
        _up(mc, steady_noise()),
        _up(mc, synth.click_train(3.0, SR, 6.0)),
        _up(mc, tone_melody()),
    ]
    run_jobs(mc)
    return out


def _render(c: TestClient, rids: list[str], **kw) -> dict:  # type: ignore[no-untyped-def,type-arg]
    r = c.post("/api/compositions", json={"recording_ids": rids, "duration_s": 20, **kw})
    assert r.status_code in (200, 202), r.text
    _services(c).compositions.run_pending()
    return c.get(f"/api/compositions/{r.json()['id']}").json()  # type: ignore[no-any-return]


def test_create_render_and_inspect(mc: TestClient, ids: list[str]) -> None:
    comp = _render(mc, ids, seed=5)
    assert (
        comp["status"] == "ready" and comp["plan_hash"] and comp["metrics"]["clipping_ratio"] == 0
    )
    assert len(comp["sources"]) == 3 and all(s["exists"] and s["role"] for s in comp["sources"])
    assert comp["tracks"] and all(
        t["stem_url"] and t["original_url"].endswith("/audio") for t in comp["tracks"]
    )
    assert [s["name"] for s in comp["sections"]][0] == "introduction"
    assert comp["echo"][-1]["text"].startswith("This is what your world sounds like")

    master = mc.get(comp["master_url"])
    assert master.status_code == 200 and master.headers["content-type"] == "audio/wav"
    data, sr = sf.read(io.BytesIO(master.content))
    assert sr == SR and data.shape[1] == 2 and abs(len(data) / sr - comp["duration_s"]) < 0.01
    assert hashlib.sha256(master.content).hexdigest() == comp["master_sha256"]
    stem = mc.get(comp["tracks"][0]["stem_url"])
    assert stem.status_code == 200 and len(sf.read(io.BytesIO(stem.content))[0]) == len(data)

    events = mc.get(f"/api/compositions/{comp['id']}/events").json()
    assert len(events) > 10
    rec_ids = {t["recording_id"] for t in comp["tracks"]}
    for e in events:
        assert e["recording_id"] in rec_ids and e["source_start_s"] < e["source_end_s"]
    tr = mc.get(f"/api/compositions/{comp['id']}/trace/{events[0]['seq']}").json()
    assert (
        tr["source"]["exists"]
        and tr["specimen"]["geometry_hash"]
        and tr["event"]["seq"] == events[0]["seq"]
    )
    assert mc.get(f"/api/compositions/{comp['id']}/trace/99999").status_code == 404


def test_create_is_idempotent_and_variation_differs(mc: TestClient, ids: list[str]) -> None:
    body = {"recording_ids": ids, "seed": 9, "duration_s": 20}
    a = mc.post("/api/compositions", json=body)
    b = mc.post("/api/compositions", json=body)
    assert a.status_code == 202 and b.status_code == 200 and a.json()["id"] == b.json()["id"]
    assert b.json()["created"] is False
    # order of ids does not matter
    c = mc.post("/api/compositions", json={**body, "recording_ids": list(reversed(ids))})
    assert c.json()["id"] == a.json()["id"]
    _services(mc).compositions.run_pending()
    v = mc.post(f"/api/compositions/{a.json()['id']}/variation", json={})
    assert v.status_code == 202 and v.json()["parent_id"] == a.json()["id"]
    _services(mc).compositions.run_pending()
    v1 = mc.get(f"/api/compositions/{v.json()['id']}").json()
    a1 = mc.get(f"/api/compositions/{a.json()['id']}").json()
    assert (
        v1["status"] == "ready" and v1["seed"] != a1["seed"] and v1["plan_hash"] != a1["plan_hash"]
    )
    assert len(mc.get("/api/compositions").json()) == 2
    assert len(mc.get(f"/api/compositions?recording_id={ids[0]}").json()) == 2


def test_same_audio_same_seed_is_reproducible_across_installs(tmp_path: Path) -> None:
    metas = []
    for name in ("one", "two"):
        app = create_app(make_settings(tmp_path / name), web_dist=Path("/nonexistent"))
        with TestClient(app) as c:
            rids = [
                _up(c, steady_noise()),
                _up(c, synth.click_train(3.0, SR, 6.0)),
                _up(c, tone_melody()),
            ]
            run_jobs(c)
            metas.append(_render(c, rids, seed=77))
    assert metas[0]["plan_hash"] == metas[1]["plan_hash"]
    assert metas[0]["master_sha256"] == metas[1]["master_sha256"]


def test_save_name_and_reopen_after_restart(tmp_path: Path) -> None:
    s = make_settings(tmp_path)
    with TestClient(create_app(s, web_dist=Path("/nonexistent"))) as c:
        rids = [_up(c, steady_noise()), _up(c, tone_melody())]
        run_jobs(c)
        comp = _render(c, rids, seed=3)
        p = c.patch(f"/api/compositions/{comp['id']}", json={"name": "Dawn walk", "saved": True})
        assert p.json()["saved"] and p.json()["name"] == "Dawn walk"
        sha = comp["master_sha256"]
        events = c.get(f"/api/compositions/{comp['id']}/events").json()
    with TestClient(create_app(s, web_dist=Path("/nonexistent"))) as c2:
        again = c2.get(f"/api/compositions/{comp['id']}").json()
        assert again["status"] == "ready" and again["saved"] and again["name"] == "Dawn walk"
        assert c2.get(again["master_url"]).content[:4] == b"RIFF"
        assert hashlib.sha256(c2.get(again["master_url"]).content).hexdigest() == sha
        assert c2.get(f"/api/compositions/{comp['id']}/events").json() == events


def test_export_wav_and_bundle(mc: TestClient, ids: list[str]) -> None:
    comp = _render(mc, ids, seed=1, name="My orchestra")
    r = mc.get(comp["export_url"])
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    assert r.content[:4] == b"RIFF"
    z = zipfile.ZipFile(io.BytesIO(mc.get(comp["export_url"] + "?bundle=true").content))
    names = z.namelist()
    assert "master.wav" in names and "plan.json" in names and "provenance.json" in names
    assert sum(n.startswith("stems/") for n in names) == len(comp["tracks"])
    prov = json.loads(z.read("provenance.json"))
    assert prov["seed"] == 1 and len(prov["sources"]) == 3 and "background speech" in prov["note"]


def test_validation_errors(mc: TestClient, ids: list[str]) -> None:
    assert mc.post("/api/compositions", json={"recording_ids": []}).status_code == 422
    assert mc.post("/api/compositions", json={"recording_ids": ["nope"]}).status_code == 404
    missing = "0197a0a0-0000-7000-8000-000000000000"
    assert mc.post("/api/compositions", json={"recording_ids": [missing]}).status_code == 404
    assert (
        mc.post(
            "/api/compositions", json={"recording_ids": ids, "controls": {"warp": 1}}
        ).status_code
        == 422
    )
    assert (
        mc.post(
            "/api/compositions", json={"recording_ids": ids, "role_overrides": {ids[0]: "kazoo"}}
        ).status_code
        == 422
    )
    assert (
        mc.post("/api/compositions", json={"recording_ids": ids, "duration_s": 5}).status_code
        == 422
    )
    assert mc.get("/api/compositions/not-an-id").status_code == 404


def test_recording_not_ready_is_refused(mc: TestClient) -> None:
    rid = _up(mc, steady_noise())  # worker disabled: still 'uploaded'
    r = mc.post("/api/compositions", json={"recording_ids": [rid]})
    assert r.status_code == 409 and r.json()["code"] == "NOT_READY"


def test_failed_render_keeps_recordings_and_can_retry(
    mc: TestClient, ids: list[str], monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    import unheard.music.service as svc

    real = svc.compose
    monkeypatch.setattr(svc, "compose", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    r = mc.post("/api/compositions", json={"recording_ids": ids, "duration_s": 20, "seed": 2})
    _services(mc).compositions.run_pending()
    comp = mc.get(f"/api/compositions/{r.json()['id']}").json()
    assert comp["status"] == "failed" and "boom" in comp["error"] and comp["master_url"] is None
    assert mc.get(f"/api/compositions/{comp['id']}/master").status_code == 409
    assert all(mc.get(f"/api/recordings/{i}").json()["status"] == "ready" for i in ids)
    assert mc.get(f"/api/recordings/{ids[0]}/audio").status_code == 200
    assert not (_services(mc).settings.data_dir / "compositions").exists() or not any(
        (_services(mc).settings.data_dir / "compositions").rglob("master.wav")
    )
    monkeypatch.setattr(svc, "compose", real)
    assert mc.post(f"/api/compositions/{comp['id']}/render").status_code == 202
    _services(mc).compositions.run_pending()
    assert mc.get(f"/api/compositions/{comp['id']}").json()["status"] == "ready"


def test_interrupted_render_is_requeued_on_start(mc: TestClient, ids: list[str]) -> None:
    r = mc.post("/api/compositions", json={"recording_ids": ids, "duration_s": 20})
    cid = r.json()["id"]
    with _services(mc).db.transaction() as conn:
        conn.execute("UPDATE composition SET status='processing' WHERE id=?", (cid,))
    _services(mc).compositions.start()
    _services(mc).compositions.stop()
    _services(mc).compositions.run_pending()
    assert mc.get(f"/api/compositions/{cid}").json()["status"] == "ready"


def test_delete_composition_removes_files(mc: TestClient, ids: list[str]) -> None:
    comp = _render(mc, ids, seed=4)
    root = _services(mc).settings.data_dir / "compositions"
    assert any(root.rglob("master.wav"))
    assert mc.delete(f"/api/compositions/{comp['id']}").status_code == 204
    assert not any(root.rglob("master.wav"))
    assert mc.get(f"/api/compositions/{comp['id']}").status_code == 404
    assert mc.delete(f"/api/compositions/{comp['id']}").status_code == 404


def test_deleting_a_source_recording_deletes_its_compositions(
    mc: TestClient, ids: list[str]
) -> None:
    c1 = _render(mc, ids, seed=1)
    c2 = _render(mc, ids[:2], seed=1)
    assert mc.delete(f"/api/recordings/{ids[2]}").status_code == 204
    assert mc.get(f"/api/compositions/{c1['id']}").status_code == 404  # contained the deleted sound
    assert mc.get(f"/api/compositions/{c2['id']}").json()["status"] == "ready"  # untouched
    ev = _services(mc).db.connection()
    with ev as conn:
        n = conn.execute(
            "SELECT COUNT(*) FROM event WHERE type='CompositionDeleted' AND payload_json LIKE '%source_deleted%'"
        ).fetchone()[0]
    assert n == 1


def test_events_are_logged(mc: TestClient, ids: list[str]) -> None:
    _render(mc, ids, seed=6)
    with _services(mc).db.connection() as conn:
        types = [
            r["type"] for r in conn.execute("SELECT type FROM event ORDER BY created_at, rowid")
        ]
    for t in ("CompositionCreated", "CompositionPlanned", "CompositionRendered"):
        assert t in types


def test_role_override_changes_the_plan(mc: TestClient, ids: list[str]) -> None:
    a = _render(mc, ids, seed=2)
    b = _render(mc, ids, seed=2, role_overrides={ids[0]: "granular"})
    assert b["plan_hash"] != a["plan_hash"]
    role = next(s for s in b["sources"] if s["recording_id"] == ids[0])
    assert role["role"] == "granular" and role["decision"]["overridden"]
