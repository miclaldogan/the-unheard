"""HTTP-level tests through the FastAPI app (worker driven synchronously)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.conftest import make_settings, run_jobs
from tests.fixtures import synth
from unheard.app import create_app

SR = 48_000


def upload(client: TestClient, data: bytes, name: str = "clip.wav", mime: str = "audio/wav"):
    return client.post("/api/recordings", files={"file": (name, data, mime)})


def test_health(client: TestClient) -> None:
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok" and body["dsp_version"] == 1 and body["schema_version"] == 3
    assert body["inference"] == "local" and body["model_loaded"] is False
    assert body["limits"]["max_duration_s"] == 30.0


def test_upload_process_retrieve(client: TestClient) -> None:
    r = upload(client, synth.wav_bytes(synth.environmental_like(SR, 4.0), SR))
    assert r.status_code == 202, r.text
    body = r.json()
    rid = body["recording_id"]
    assert body["status"] == "uploaded" and body["links"]["features"].endswith("/features")

    # not ready yet → 409 with NOT_READY
    f = client.get(f"/api/recordings/{rid}/features")
    assert f.status_code == 409 and f.json()["code"] == "NOT_READY"
    assert f.headers["content-type"].startswith("application/problem+json")

    assert run_jobs(client) == 1
    d = client.get(f"/api/recordings/{rid}").json()
    assert d["status"] == "ready" and d["dsp_version"] == 1
    assert d["inference"]["status"] == "not_run" and d["inference"]["predictions"] == []
    assert {a["kind"] for a in d["assets"]} == {"source", "canonical"}
    assert d["features"]["duration_s"] == pytest.approx(4.0, abs=0.01)

    f = client.get(f"/api/recordings/{rid}/features").json()
    assert f["dsp_version"] == 1 and len(f["waveform"]["min"]) == 1200
    assert len(f["series"]["times_s"]) == len(f["series"]["centroid_hz"]) > 0
    assert f["summary"]["onset_count"] >= 3  # three synthetic clicks

    s = client.get(f"/api/recordings/{rid}/spectrogram?max_frames=128").json()
    assert s["kind"] == "mel" and s["n_bins"] == 64 and s["n_frames"] <= 128
    assert len(s["values"]) == 64 and len(s["values"][0]) == s["n_frames"]
    s2 = client.get(f"/api/recordings/{rid}/spectrogram?kind=stft").json()
    assert s2["n_bins"] == 256

    lst = client.get("/api/recordings").json()
    assert lst["total"] == 1 and lst["items"][0]["id"] == rid


def test_audio_playback_returns_original_bytes(client: TestClient) -> None:
    data = synth.flac_bytes(synth.sine(440, SR, 3.0), SR)
    rid = upload(client, data, "x.flac", "audio/flac").json()["recording_id"]
    a = client.get(f"/api/recordings/{rid}/audio")
    assert a.status_code == 200 and a.content == data
    assert a.headers["content-type"].startswith("audio/flac")
    c = client.get(f"/api/recordings/{rid}/audio?variant=canonical")
    assert c.status_code == 200 and c.content[:4] == b"RIFF"


def test_invalid_files_rejected(client: TestClient) -> None:
    r = upload(client, b"%PDF-1.4 definitely not audio" * 20, "a.wav")
    assert r.status_code == 415 and r.json()["code"] == "AUDIO_UNSUPPORTED_FORMAT"
    r = upload(client, synth.wav_bytes(synth.sine(440, SR, 1.0), SR))
    assert r.status_code == 422 and r.json()["code"] == "AUDIO_TOO_SHORT"
    r = upload(client, synth.wav_bytes(synth.silence(SR, 4.0), SR))
    assert r.status_code == 422 and r.json()["code"] == "AUDIO_SILENT"
    r = upload(client, b"RIFF\0\0\0\0WAVE" + b"\xff" * 200)
    assert r.status_code == 422 and r.json()["code"] == "AUDIO_UNDECODABLE"
    r = client.post("/api/recordings", data={})
    assert r.status_code == 422 and r.json()["code"] == "VALIDATION_FAILED"
    assert client.get("/api/recordings").json()["total"] == 0


def test_oversized_upload_413(tmp_path: Path) -> None:
    app = create_app(
        make_settings(tmp_path, max_upload_bytes=50_000), web_dist=Path("/nonexistent")
    )
    with TestClient(app) as c:
        r = upload(c, synth.wav_bytes(synth.sine(440, SR, 3.0), SR))
        assert r.status_code == 413 and r.json()["code"] == "AUDIO_TOO_LARGE"


def test_duplicate_409(client: TestClient) -> None:
    data = synth.wav_bytes(synth.sine(440, SR, 3.0), SR)
    first = upload(client, data).json()["recording_id"]
    r = upload(client, data)
    assert r.status_code == 409 and r.json()["recording_id"] == first


def test_unknown_and_malicious_ids(client: TestClient) -> None:
    for bad in ["nope", "../../etc/passwd", "0199a000-0000-7000-8000-000000000000"]:
        r = client.get(f"/api/recordings/{bad}")
        assert r.status_code == 404, bad
    r = client.get("/api/recordings/..%2F..%2Fetc%2Fpasswd/audio")
    assert r.status_code == 404


def test_delete_removes_rows_and_files(client: TestClient) -> None:
    rid = upload(client, synth.wav_bytes(synth.sine(440, SR, 3.0), SR)).json()["recording_id"]
    run_jobs(client)
    blobs = client.app.state.services.blobs  # type: ignore[attr-defined]
    rec_dir_audio = blobs.absolute(f"audio/{rid[:2]}/{rid}")
    rec_dir_art = blobs.absolute(f"artifacts/{rid[:2]}/{rid}")
    assert rec_dir_audio.is_dir() and rec_dir_art.is_dir()
    r = client.delete(f"/api/recordings/{rid}")
    assert r.status_code == 204
    assert not rec_dir_audio.exists() and not rec_dir_art.exists()
    assert client.get(f"/api/recordings/{rid}").status_code == 404
    assert client.get(f"/api/recordings/{rid}/audio").status_code == 404
    assert client.delete(f"/api/recordings/{rid}").status_code == 404
    with client.app.state.services.db.connection() as conn:  # type: ignore[attr-defined]
        assert conn.execute("SELECT COUNT(*) FROM feature_set").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM job").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM audio_asset").fetchone()[0] == 0
        types = [r[0] for r in conn.execute("SELECT type FROM event ORDER BY created_at")]
    assert [t for t in types if t != "ArtifactRendered"] == [
        "RecordingCaptured",
        "FeaturesExtracted",
        "RecordingDeleted",
    ]


def test_processing_failure_is_inspectable_and_retryable(client: TestClient) -> None:
    rid = upload(client, synth.wav_bytes(synth.sine(440, SR, 3.0), SR)).json()["recording_id"]
    services = client.app.state.services  # type: ignore[attr-defined]
    canonical = services.blobs.absolute(f"audio/{rid[:2]}/{rid}/canonical.wav")
    good = canonical.read_bytes()
    canonical.write_bytes(b"RIFF broken")  # sabotage the canonical file
    run_jobs(client)
    d = client.get(f"/api/recordings/{rid}").json()
    assert (
        d["status"] == "failed"
        and d["error"]["stage"] == "dsp"
        and d["jobs"][0]["status"] == "failed"
    )
    assert client.get(f"/api/recordings/{rid}/features").status_code == 409
    # the raw upload is still there and playable
    assert client.get(f"/api/recordings/{rid}/audio").status_code == 200
    # repair and retry
    canonical.write_bytes(good)
    r = client.post(f"/api/recordings/{rid}/retry")
    assert r.status_code == 202
    run_jobs(client)
    d = client.get(f"/api/recordings/{rid}").json()
    assert d["status"] == "ready" and d["error"] is None


def test_persistence_across_app_restart(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    data = synth.wav_bytes(synth.environmental_like(SR, 3.0), SR)
    with TestClient(create_app(settings, web_dist=Path("/nonexistent"))) as c:
        rid = upload(c, data).json()["recording_id"]
        run_jobs(c)
    # new app instance, same data dir → recording, features, audio all present
    with TestClient(create_app(settings, web_dist=Path("/nonexistent"))) as c:
        d = c.get(f"/api/recordings/{rid}").json()
        assert d["status"] == "ready" and d["features"] is not None
        assert c.get(f"/api/recordings/{rid}/audio").content == data
        assert c.get(f"/api/recordings/{rid}/features").status_code == 200


def test_running_jobs_reset_on_restart(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    with TestClient(create_app(settings, web_dist=Path("/nonexistent"))) as c:
        rid = upload(c, synth.wav_bytes(synth.sine(440, SR, 3.0), SR)).json()["recording_id"]
        with c.app.state.services.db.connection() as conn:  # type: ignore[attr-defined]
            conn.execute("UPDATE job SET status='running'")
    with TestClient(create_app(settings, web_dist=Path("/nonexistent"))) as c:
        c.app.state.services.worker.start()  # type: ignore[attr-defined]
        c.app.state.services.worker.stop()  # type: ignore[attr-defined]
        with c.app.state.services.db.connection() as conn:  # type: ignore[attr-defined]
            status = conn.execute("SELECT status FROM job").fetchone()[0]
        assert status in ("queued", "done")
        run_jobs(c)
        assert c.get(f"/api/recordings/{rid}").json()["status"] == "ready"


def test_bearer_token_required_when_configured(tmp_path: Path) -> None:
    app = create_app(
        make_settings(tmp_path, api_token="secret-token"), web_dist=Path("/nonexistent")
    )
    with TestClient(app) as c:
        assert c.get("/api/health").status_code == 200
        assert c.get("/api/recordings").status_code == 401
        assert (
            c.get("/api/recordings", headers={"Authorization": "Bearer wrong"}).status_code == 401
        )
        assert (
            c.get("/api/recordings", headers={"Authorization": "Bearer secret-token"}).status_code
            == 200
        )
