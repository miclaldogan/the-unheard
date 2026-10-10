"""M6: a label given before inference finishes becomes an acoustic exemplar exactly once, never twice, never for a ghost."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.conftest import make_settings, run_jobs
from tests.fakes import install_fake
from tests.fixtures import synth
from unheard.app import create_app
from unheard.storage.repos import EventRepo

SR = 48_000


@pytest.fixture
def c(tmp_path: Path):
    app = create_app(make_settings(tmp_path, model_name="fake/clap"), web_dist=Path("/nonexistent"))
    with TestClient(app) as client:
        install_fake(client.app.state.services)  # type: ignore[attr-defined]
        yield client


def upload(c: TestClient, f: float = 440.0) -> str:
    x = synth.sine(f, SR, 4.0, amp=0.4)
    r = c.post("/api/recordings", files={"file": ("a.wav", synth.wav_bytes(x, SR), "audio/wav")})
    assert r.status_code == 202, r.text
    return str(r.json()["recording_id"])


def annotate(c: TestClient, rid: str, **body: Any) -> dict[str, Any]:
    r = c.post(f"/api/recordings/{rid}/annotations", json=body)
    assert r.status_code == 201, r.text
    return dict(r.json())


def memory(c: TestClient) -> dict[str, Any]:
    return dict(c.get("/api/memory").json())


def memory_events(c: TestClient, rid: str) -> list[dict[str, Any]]:
    db = c.app.state.services.db  # type: ignore[attr-defined]
    with db.connection() as conn:
        return [
            e for e in EventRepo.for_recording(conn, rid) if e["type"] == "AcousticMemoryUpdated"
        ]


def test_label_before_inference_is_stored_but_flagged_pending(c: TestClient) -> None:
    rid = upload(c)
    res = annotate(c, rid, new_labels=["Gate"])
    assert res["memory_pending"] is True and res["exemplars_added"] == 0
    assert memory(c)["exemplars"] == 0
    assert c.get(f"/api/recordings/{rid}/annotations").json()[0]["status"] == "active"


def test_inference_backfills_the_stored_annotation_once(c: TestClient) -> None:
    rid = upload(c)
    annotate(c, rid, new_labels=["Gate"])
    run_jobs(c)  # dsp -> infer
    mem = memory(c)
    assert mem["exemplars"] == 1 and mem["annotations"] == 1
    reasons = [e["payload"]["reason"] for e in memory_events(c, rid)]
    assert reasons.count("annotation_backfill") == 1
    fused = c.get(f"/api/recordings/{rid}/prediction").json()["fused"]
    assert fused["memory_version"] >= 1


def test_retry_and_reinference_do_not_duplicate_exemplars(c: TestClient) -> None:
    rid = upload(c)
    annotate(c, rid, new_labels=["Gate"])
    run_jobs(c)
    for _ in range(2):
        assert c.post(f"/api/recordings/{rid}/infer").status_code == 202
        run_jobs(c)
    assert memory(c)["exemplars"] == 1
    reasons = [e["payload"]["reason"] for e in memory_events(c, rid)]
    assert reasons.count("annotation_backfill") == 1


def test_correction_while_pending_only_the_latest_label_is_learned(c: TestClient) -> None:
    rid = upload(c)
    annotate(c, rid, new_labels=["Gate"])
    annotate(c, rid, new_labels=["Hinge"])
    run_jobs(c)
    mem = memory(c)
    assert mem["exemplars"] == 1
    by = {lab["name"]: lab["n_exemplars"] for lab in mem["labels"] if lab["origin"] == "user"}
    assert by.get("Hinge") == 1 and by.get("Gate", 0) == 0


def test_unknown_while_pending_adds_no_exemplar(c: TestClient) -> None:
    rid = upload(c)
    res = annotate(c, rid, is_unknown=True)
    assert res["memory_pending"] is False
    run_jobs(c)
    assert memory(c)["exemplars"] == 0


def test_recording_deleted_before_inference_leaves_no_ghost_memory(c: TestClient) -> None:
    rid = upload(c)
    annotate(c, rid, new_labels=["Gate"])
    assert c.delete(f"/api/recordings/{rid}").status_code == 204
    run_jobs(c)
    assert memory(c)["exemplars"] == 0


def test_label_after_inference_is_not_pending(c: TestClient) -> None:
    rid = upload(c)
    run_jobs(c)
    res = annotate(c, rid, new_labels=["Gate"])
    assert res["memory_pending"] is False and res["exemplars_added"] == 1


def test_narrative_does_not_claim_learning_while_memory_is_pending(tmp_path: Path) -> None:
    from tests.narrative_helpers import add_recording, make_client, tone

    c = make_client(
        tmp_path, model="none"
    )  # recording processed, ears not available: label cannot be learned
    try:
        rid = add_recording(c, tone(440.0, 1))
        annotate(c, rid, new_labels=["Gate"])
        cur = c.get("/api/narrative/current").json()["utterance"]
        assert any("memory is not updated" in f["statement"] for f in cur["facts"]), cur
    finally:
        c.__exit__(None, None, None)


def test_narrative_has_no_pending_note_once_learned(c: TestClient) -> None:
    rid = upload(c)
    run_jobs(c)
    annotate(c, rid, new_labels=["Gate"])
    cur = c.get("/api/narrative/current").json()["utterance"]
    assert not any("memory is not updated" in f["statement"] for f in cur["facts"])


def test_interrupted_inference_rolls_back_and_a_retry_learns_once(
    c: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    rid = upload(c)
    annotate(c, rid, new_labels=["Gate"])
    memory_svc = c.app.state.services.memory  # type: ignore[attr-defined]
    real = memory_svc.backfill_pending
    calls = {"n": 0}

    def flaky(*a: Any, **kw: Any) -> Any:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("worker killed mid-transaction")
        return real(*a, **kw)

    monkeypatch.setattr(memory_svc, "backfill_pending", flaky)
    run_jobs(c)  # first attempt fails inside the inference transaction
    assert memory(c)["exemplars"] == 0
    assert (
        c.get(f"/api/recordings/{rid}/annotations").json()[0]["status"] == "active"
    )  # label survives
    assert c.post(f"/api/recordings/{rid}/infer").status_code == 202
    run_jobs(c)
    assert memory(c)["exemplars"] == 1
    reasons = [e["payload"]["reason"] for e in memory_events(c, rid)]
    assert reasons.count("annotation_backfill") == 1
