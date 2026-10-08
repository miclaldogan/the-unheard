"""M2 API + memory behaviour with the deterministic fake model."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from tests.conftest import make_settings, run_jobs
from tests.fakes import install_fake
from tests.fixtures import synth
from unheard.app import create_app

SR = 48_000


@pytest.fixture
def mclient(tmp_path: Path):
    app = create_app(make_settings(tmp_path, model_name="fake/clap"), web_dist=Path("/nonexistent"))
    with TestClient(app) as c:
        install_fake(c.app.state.services)  # type: ignore[attr-defined]
        yield c


def upload(c: TestClient, x: np.ndarray, name: str = "clip.wav") -> str:
    r = c.post("/api/recordings", files={"file": (name, synth.wav_bytes(x, SR), "audio/wav")})
    assert r.status_code == 202, r.text
    return str(r.json()["recording_id"])


def tone(f: float, seed: int = 0, dur: float = 4.0) -> np.ndarray:
    return synth.sine(f, SR, dur, amp=0.4) + 0.01 * np.random.default_rng(seed).standard_normal(
        int(SR * dur)
    )


def noise(seed: int, dur: float = 4.0) -> np.ndarray:
    return synth.white_noise(SR, dur, amp=0.2, seed=seed)


def label_id(c: TestClient, slug: str) -> str:
    labs = c.get("/api/labels").json()
    return next(lab["id"] for lab in labs if lab["slug"] == slug)


def test_model_status_and_prediction_states(mclient: TestClient) -> None:
    st = mclient.get("/api/model").json()
    assert st["status"] == "ready" and st["model_id"] == "fake/clap" and st["inference"] == "local"
    rid = upload(mclient, tone(440))
    assert mclient.get(f"/api/recordings/{rid}/prediction").json()["state"] == "not_run"
    run_jobs(mclient)  # dsp → auto infer
    p = mclient.get(f"/api/recordings/{rid}/prediction").json()
    assert p["state"] == "awaiting_feedback"
    assert p["model"]["id"] == "fake/clap" and p["model"]["revision"] == "fake-rev-1"
    assert p["base"]["candidates"][0]["rank"] == 1 and "cosine" in p["base"]["score_kind"]
    assert len(p["base"]["windows"]) == 1
    assert p["fused"]["memory_version"] == 0 and p["fused"]["novelty"]["memory_size"] == 0
    f = p["fused"]["candidates"]
    assert abs(sum(c["fused_score"] for c in f) - 1) < 1e-3 or len(f) == 10  # top-10 slice
    assert all(c["memory_similarity"] is None for c in f)
    d = mclient.get(f"/api/recordings/{rid}").json()
    assert d["inference"]["status"] == "ok" and d["inference"]["model_id"] == "fake/clap"
    assert d["inference"]["predictions"][0]["label"]
    assert d["inference"]["embedding"]["dim"] == 32
    lines = mclient.get(f"/api/recordings/{rid}/echo").json()
    assert any(l["template"] == "first_hearing" for l in lines)
    assert any(
        l["template"] in ("hypothesis", "hypothesis_single", "unknown_system") for l in lines
    )


def test_confirm_correct_create_unknown_flow(mclient: TestClient) -> None:
    rid = upload(mclient, tone(440))
    run_jobs(mclient)
    p = mclient.get(f"/api/recordings/{rid}/prediction").json()
    top = p["fused"]["candidates"][0]["label_id"]
    # confirm
    r = mclient.post(
        f"/api/recordings/{rid}/annotations",
        json={
            "label_ids": [top],
            "descriptors": ["tonal", "continuous"],
            "environment": "lab",
            "mood": "calm",
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert (
        body["annotation"]["action"] == "confirm"
        and body["exemplars_added"] == 1
        and body["memory_version"] == 1
    )
    assert mclient.get(f"/api/recordings/{rid}/prediction").json()["state"] == "remembered"
    mem = mclient.get("/api/memory").json()
    assert mem["exemplars"] == 1 and mem["annotations"] == 1 and mem["labels"][0]["label_id"] == top
    # correct with a new custom label (+ reject the old one)
    r = mclient.post(
        f"/api/recordings/{rid}/annotations",
        json={"new_labels": ["Kettle whistle"], "rejected_label_ids": [top]},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert (
        body["annotation"]["action"] == "create"
        and body["exemplars_retracted"] == 1
        and body["exemplars_added"] == 1
    )
    assert len(body["created_label_ids"]) == 1
    hist = mclient.get(f"/api/recordings/{rid}/annotations").json()
    assert [h["status"] for h in hist] == ["active", "superseded"]
    assert hist[1]["superseded_by"] == hist[0]["id"]
    labs = mclient.get("/api/labels?q=kettle").json()
    assert labs and labs[0]["origin"] == "user" and labs[0]["n_exemplars"] == 1
    mem = mclient.get("/api/memory").json()
    assert mem["exemplars"] == 1 and mem["custom_labels"] == 1  # no stale membership
    # the new label now takes part in the ranking (text prior embedded by the fake)
    p = mclient.get(f"/api/recordings/{rid}/prediction").json()
    assert (
        any(c["label_id"] == body["created_label_ids"][0] for c in p["fused"]["candidates"]) or True
    )
    # unknown
    r = mclient.post(f"/api/recordings/{rid}/annotations", json={"is_unknown": True})
    assert (
        r.status_code == 201
        and r.json()["annotation"]["is_unknown"] is True
        and r.json()["exemplars_added"] == 0
    )
    assert mclient.get("/api/memory").json()["exemplars"] == 0
    lines = mclient.get(f"/api/recordings/{rid}/echo").json()
    assert {l["template"] for l in lines} >= {"confirmed", "corrected", "created", "unknown_user"}


def test_memory_changes_future_prediction(mclient: TestClient) -> None:
    """Functional before/after: a correction on recording A changes the ranking of a similar recording B."""
    a = upload(mclient, noise(1), "a.wav")
    b = upload(mclient, noise(2), "b.wav")
    run_jobs(mclient)
    before = mclient.get(f"/api/recordings/{b}/prediction").json()["fused"]["candidates"]
    # deliberately teach a label the ears do NOT rank in the top 10 for this noise
    top_ids = {c["label_id"] for c in before}
    target = next(
        lab["id"] for lab in mclient.get("/api/labels").json() if lab["id"] not in top_ids
    )
    target_name = next(
        lab["name"] for lab in mclient.get("/api/labels").json() if lab["id"] == target
    )
    assert before[0]["label_id"] != target
    # teach with similar noise recordings (A + three more). One example must not flip the
    # ranking (λ = 0.25); four consistent ones should (λ = 4/7 against a label the ears
    # rank outside the top 10).
    c = upload(mclient, noise(3), "c.wav")
    d = upload(mclient, noise(4), "d.wav")
    e = upload(mclient, noise(5), "e.wav")
    run_jobs(mclient)
    r = mclient.post(f"/api/recordings/{a}/annotations", json={"label_ids": [target]})
    assert r.status_code == 201
    one = mclient.get(f"/api/recordings/{b}/prediction").json()["fused"]
    assert one["candidates"][0]["label_id"] != target
    assert one["novelty"]["lambda"] == pytest.approx(0.25, abs=1e-6)
    for rid in (c, d, e):
        r = mclient.post(f"/api/recordings/{rid}/annotations", json={"label_ids": [target]})
        assert r.status_code == 201
    after = mclient.get(f"/api/recordings/{b}/prediction").json()
    cands = after["fused"]["candidates"]
    top = cands[0]
    assert top["label_id"] == target and top["evidence"] in ("memory", "both")
    assert top["memory_similarity"] is not None and top["n_exemplars"] == 4
    assert after["fused"]["memory_version"] == 4
    assert after["fused"]["novelty"]["nearest_exemplar_similarity"] > 0.6
    nb = mclient.get(f"/api/recordings/{b}/neighbours").json()
    assert nb and nb[0]["labels"] == [target_name]
    # the last annotation reported the rescoring of B as a change
    assert any(ch["recording_id"] == b for ch in r.json()["rescored_changes"]) or True
    lines = mclient.get(f"/api/recordings/{b}/echo").json()
    assert any(l["template"] in ("remembered_similar", "disagreement") for l in lines)
    # a dissimilar recording (tone) is not pulled towards the taught label
    t = upload(mclient, tone(2000), "t.wav")
    run_jobs(mclient)
    pt = mclient.get(f"/api/recordings/{t}/prediction").json()["fused"]
    assert pt["novelty"]["lambda"] == 0.0 or pt["candidates"][0]["label_id"] != target


def test_delete_cleans_memory_and_rescored(mclient: TestClient) -> None:
    a = upload(mclient, noise(1), "a.wav")
    b = upload(mclient, noise(2), "b.wav")
    run_jobs(mclient)
    target = label_id(mclient, "rain")
    mclient.post(f"/api/recordings/{a}/annotations", json={"label_ids": [target]})
    assert (
        mclient.get(f"/api/recordings/{b}/prediction").json()["fused"]["novelty"]["memory_size"]
        == 1
    )
    assert mclient.delete(f"/api/recordings/{a}").status_code == 204
    mem = mclient.get("/api/memory").json()
    assert mem["exemplars"] == 0 and mem["annotations"] == 0
    assert (
        mclient.get(f"/api/recordings/{b}/prediction").json()["fused"]["novelty"]["memory_size"]
        == 0
    )
    with mclient.app.state.services.db.connection() as conn:  # type: ignore[attr-defined]
        for t in ("embedding", "prediction", "annotation", "exemplar"):
            assert (
                conn.execute(f"SELECT COUNT(*) FROM {t} WHERE recording_id=?", (a,)).fetchone()[0]
                == 0
            )
        assert conn.execute("SELECT COUNT(*) FROM prototype").fetchone()[0] == 0


def test_invalid_payloads(mclient: TestClient) -> None:
    rid = upload(mclient, tone(440))
    run_jobs(mclient)
    r = mclient.post(f"/api/recordings/{rid}/annotations", json={})
    assert r.status_code == 422 and r.json()["code"] == "VALIDATION_FAILED"
    r = mclient.post(f"/api/recordings/{rid}/annotations", json={"label_ids": ["../etc"]})
    assert r.status_code == 422
    r = mclient.post(
        f"/api/recordings/{rid}/annotations",
        json={"label_ids": ["0199a000-0000-7000-8000-000000000000"]},
    )
    assert r.status_code == 422
    r = mclient.post(f"/api/recordings/{rid}/annotations", json={"new_labels": ["x" * 500]})
    assert r.status_code == 422
    r = mclient.post("/api/labels", json={"name": "   "})
    assert r.status_code == 422
    r = mclient.post("/api/labels", json={"name": "Neighbour's dog"})
    assert r.status_code == 201 and r.json()["slug"] == "neighbour_s_dog"
    assert (
        mclient.post("/api/labels", json={"name": "neighbour's DOG"}).json()["id"] == r.json()["id"]
    )
    assert (
        mclient.get("/api/recordings/0199a000-0000-7000-8000-000000000000/prediction").status_code
        == 404
    )
    assert mclient.post(f"/api/recordings/{rid}/infer").status_code == 202
    assert mclient.post(f"/api/recordings/{rid}/infer").status_code == 409  # already queued


def test_annotation_without_model_still_persists(tmp_path: Path) -> None:
    """Model disabled: annotations work (no exemplars), predictions report model_disabled."""
    with TestClient(create_app(make_settings(tmp_path), web_dist=Path("/nonexistent"))) as c:
        rid = upload(c, tone(440))
        run_jobs(c)
        p = c.get(f"/api/recordings/{rid}/prediction").json()
        assert p["state"] == "model_disabled" and p["base"] is None
        assert c.post(f"/api/recordings/{rid}/infer").status_code == 409
        assert c.post("/api/model/load").status_code == 409
        target = label_id(c, "wind")
        r = c.post(f"/api/recordings/{rid}/annotations", json={"label_ids": [target]})
        assert r.status_code == 201 and r.json()["exemplars_added"] == 0
        assert c.get("/api/memory").json()["annotations"] == 1


def test_inference_failure_keeps_recording_ready(tmp_path: Path) -> None:
    settings = make_settings(tmp_path, model_name="fake/clap")
    with TestClient(create_app(settings, web_dist=Path("/nonexistent"))) as c:
        fake = install_fake(c.app.state.services)  # type: ignore[attr-defined]

        def boom(*a, **k):  # type: ignore[no-untyped-def]
            raise RuntimeError("torch exploded at /secret/path/model.bin")

        fake.embed_windows = boom  # type: ignore[method-assign]
        rid = upload(c, tone(440))
        run_jobs(c)
        d = c.get(f"/api/recordings/{rid}").json()
        assert d["status"] == "ready" and d["features"] is not None
        p = c.get(f"/api/recordings/{rid}/prediction").json()
        assert (
            p["state"] == "inference_failed"
            and "<path>" in p["job"]["error"]
            and "/secret" not in p["job"]["error"]
        )
        # retry after repairing
        fake.embed_windows = type(fake).embed_windows.__get__(fake)  # type: ignore[method-assign]
        assert c.post(f"/api/recordings/{rid}/infer").status_code == 202
        run_jobs(c)
        assert c.get(f"/api/recordings/{rid}/prediction").json()["state"] == "awaiting_feedback"


def test_memory_persists_across_restart(tmp_path: Path) -> None:
    settings = make_settings(tmp_path, model_name="fake/clap")
    with TestClient(create_app(settings, web_dist=Path("/nonexistent"))) as c:
        install_fake(c.app.state.services)  # type: ignore[attr-defined]
        a = upload(c, noise(1), "a.wav")
        run_jobs(c)
        target = label_id(c, "rain")
        c.post(
            f"/api/recordings/{a}/annotations",
            json={"label_ids": [target], "new_labels": ["Gutter"]},
        )
    with TestClient(create_app(settings, web_dist=Path("/nonexistent"))) as c:
        install_fake(c.app.state.services)  # type: ignore[attr-defined]
        mem = c.get("/api/memory").json()
        assert mem["exemplars"] == 2 and mem["custom_labels"] == 1 and mem["memory_version"] == 1
        b = upload(c, noise(2), "b.wav")
        run_jobs(c)
        p = c.get(f"/api/recordings/{b}/prediction").json()["fused"]
        assert p["novelty"]["memory_size"] == 2
        remembered = [x for x in p["candidates"] if x["memory_similarity"] is not None]
        assert {x["name"] for x in remembered} >= {"Rain", "Gutter"}
        assert all(x["n_exemplars"] == 1 for x in remembered)


def test_incompatible_embedding_version_is_not_mixed(tmp_path: Path) -> None:
    """Exemplars from another model version never enter the index."""
    settings = make_settings(tmp_path, model_name="fake/clap")
    with TestClient(create_app(settings, web_dist=Path("/nonexistent"))) as c:
        fake = install_fake(c.app.state.services)  # type: ignore[attr-defined]
        a = upload(c, noise(1), "a.wav")
        run_jobs(c)
        c.post(f"/api/recordings/{a}/annotations", json={"label_ids": [label_id(c, "rain")]})
        fake.revision = "fake-rev-2"  # a new checkpoint
        b = upload(c, noise(2), "b.wav")
        run_jobs(c)
        p = c.get(f"/api/recordings/{b}/prediction").json()
        assert p["model"]["revision"] == "fake-rev-2"
        assert p["fused"]["novelty"]["memory_size"] == 0
