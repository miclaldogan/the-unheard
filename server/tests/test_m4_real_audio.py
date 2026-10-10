"""Real recordings → DSP → roles → plan → render → persistent WAV → provenance.

Uses ESC-50 clips (CC BY-NC 3.0, local evaluation only; see eval/README.md). Skipped when the
clips are not present, so CI without the dataset stays green.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest
import soundfile as sf
from fastapi.testclient import TestClient

from tests.conftest import make_settings, run_jobs
from unheard.app import create_app

ESC = Path(__file__).resolve().parents[1] / "data" / "eval" / "esc50"
SETS = {
    "natural": ["1-12653-A-15.wav", "1-34495-A-14.wav", "1-137296-A-16.wav", "1-17367-A-10.wav"],
    "urban": ["1-155858-A-25.wav", "1-22882-A-44.wav", "1-24074-A-43.wav", "1-21935-A-38.wav"],
    "hybrid": ["1-17367-A-10.wav", "1-13572-A-46.wav", "1-155858-A-25.wav", "1-19840-A-36.wav"],
}
pytestmark = [
    pytest.mark.real_audio,
    pytest.mark.skipif(not (ESC / "esc50.csv").exists(), reason="ESC-50 clips not downloaded"),
]


def _run(tmp: Path, files: list[str], seed: int = 7) -> tuple[TestClient, dict, list[str]]:  # type: ignore[type-arg]
    c = TestClient(create_app(make_settings(tmp), web_dist=Path("/nonexistent")))
    c.__enter__()
    ids = []
    for f in files:
        r = c.post("/api/recordings", files={"file": (f, (ESC / f).read_bytes(), "audio/wav")})
        assert r.status_code == 202, r.text
        ids.append(r.json()["recording_id"])
    run_jobs(c)
    r = c.post("/api/compositions", json={"recording_ids": ids, "seed": seed, "duration_s": 40})
    assert r.status_code == 202, r.text
    c.app.state.services.compositions.run_pending()  # type: ignore[attr-defined]
    return c, c.get(f"/api/compositions/{r.json()['id']}").json(), ids


@pytest.mark.parametrize("name", list(SETS))
def test_real_recordings_become_a_valid_composition(tmp_path: Path, name: str) -> None:
    c, comp, ids = _run(tmp_path / name, SETS[name])
    with c:
        assert comp["status"] == "ready", comp["error"]
        m = comp["metrics"]
        assert m["peak_dbfs"] <= -0.99 and m["clipping_ratio"] == 0.0
        assert m["silence_ratio"] < 0.25 and m["empty_sections"] == []
        assert -22 < m["lufs_approx"] < -14
        assert m["events_out_of_bounds"] == 0 and not m["highly_repetitive"]
        assert all(v > 0.02 for v in m["track_contribution"].values())  # every layer audible
        # real audio → persistent WAV
        wav = c.get(comp["master_url"]).content
        data, sr = sf.read(io.BytesIO(wav))
        assert sr == 48_000 and abs(len(data) / sr - comp["duration_s"]) < 0.01
        # roles come from measurements and carry evidence
        assert {s["recording_id"] for s in comp["sources"]} == set(ids)
        assert all(
            s["decision"]["evidence"] and s["decision"]["rationale"] for s in comp["sources"]
        )
        # provenance: composition → track → event → source recording → specimen
        events = c.get(f"/api/compositions/{comp['id']}/events").json()
        assert len(events) > 20
        for e in events[:: max(1, len(events) // 12)]:
            t = c.get(f"/api/compositions/{comp['id']}/trace/{e['seq']}").json()
            assert t["source"]["exists"] and t["source"]["recording_id"] in ids
            assert t["specimen"]["geometry_hash"]
            assert (
                0
                <= t["event"]["source_start_s"]
                < t["event"]["source_end_s"]
                <= t["source"]["duration_s"] + 1e-6
            )


def test_real_world_determinism_and_contrast(tmp_path: Path) -> None:
    c1, a, _ = _run(tmp_path / "a", SETS["natural"])
    c1.close()
    c2, b, _ = _run(tmp_path / "b", SETS["natural"])
    c2.close()
    assert a["master_sha256"] == b["master_sha256"]  # byte-identical in the same environment
    c3, u, _ = _run(tmp_path / "u", SETS["urban"])
    c3.close()
    assert u["master_sha256"] != a["master_sha256"]
    roles_a = sorted(s["role"] for s in a["sources"])
    roles_u = sorted(s["role"] for s in u["sources"])
    assert roles_a != roles_u  # different environments are scored differently
