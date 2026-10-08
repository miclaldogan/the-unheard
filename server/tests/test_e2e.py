"""End-to-end backend flow on a real encoded fixture, no mocks:
upload → decode → extract → persist → retrieve → delete.

The fixture is a WAV file written to a temp directory during the test (and, when ffmpeg
is present, the same audio encoded to webm/opus exactly as Chrome's MediaRecorder would send).
"""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from tests.conftest import HAS_FFMPEG, make_settings
from tests.fixtures import synth
from unheard.app import create_app

SR = 48_000


@pytest.mark.parametrize(
    "encoding",
    ["wav", pytest.param("webm", marks=pytest.mark.skipif(not HAS_FFMPEG, reason="needs ffmpeg"))],
)
def test_full_lifecycle_with_background_worker(tmp_path: Path, encoding: str) -> None:
    settings = make_settings(tmp_path, worker_enabled=True, worker_poll_s=0.05)
    x = synth.environmental_like(SR, 5.0, seed=11)
    wav = synth.wav_bytes(x, SR)
    fixture = tmp_path / f"fixture.{encoding}"
    fixture.write_bytes(wav if encoding == "wav" else synth.ffmpeg_encode(wav, "webm", "libopus"))

    with TestClient(create_app(settings, web_dist=Path("/nonexistent"))) as c:
        t0 = time.perf_counter()
        with fixture.open("rb") as fh:
            r = c.post(
                "/api/recordings",
                files={"file": (fixture.name, fh, f"audio/{encoding}")},
                data={"captured_at": "2026-10-09T10:00:00Z", "device_info": '{"ua":"pytest"}'},
            )
        assert r.status_code == 202, r.text
        rid = r.json()["recording_id"]
        t_upload = time.perf_counter() - t0

        # poll the status like the browser does
        deadline = time.time() + 20
        while time.time() < deadline:
            d = c.get(f"/api/recordings/{rid}").json()
            if d["status"] in ("ready", "failed"):
                break
            time.sleep(0.05)
        t_total = time.perf_counter() - t0
        assert d["status"] == "ready", d
        assert d["device_info"] == {"ua": "pytest"} and d["captured_at"] == "2026-10-09T10:00:00Z"
        assert d["duration_s"] == pytest.approx(5.0, abs=0.1)

        f = c.get(f"/api/recordings/{rid}/features").json()
        s = c.get(f"/api/recordings/{rid}/spectrogram").json()
        assert f["summary"]["dsp_version"] == 1
        assert f["summary"]["onset_count"] >= 3
        assert 1000 < f["summary"]["spectral_centroid_hz"]["mean"] < 12000
        assert s["n_bins"] == 64 and np.isfinite(np.asarray(s["values"])).all()
        assert s["min_db"] < s["max_db"]

        audio = c.get(f"/api/recordings/{rid}/audio")
        assert audio.status_code == 200 and audio.content == fixture.read_bytes()

        assert c.delete(f"/api/recordings/{rid}").status_code == 204
        assert c.get(f"/api/recordings/{rid}").status_code == 404
        data_root = settings.data_dir
        assert (
            not any(p.is_file() for p in (data_root / "audio").rglob("*"))
            if (data_root / "audio").exists()
            else True
        )
        assert (
            not any(p.is_file() for p in (data_root / "artifacts").rglob("*"))
            if (data_root / "artifacts").exists()
            else True
        )
        print(
            f"\n[e2e {encoding}] upload+ingest {t_upload * 1000:.0f} ms, "
            f"upload→ready {t_total * 1000:.0f} ms"
        )
