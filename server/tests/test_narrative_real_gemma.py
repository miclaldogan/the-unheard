"""Smoke test against a real local Gemma (Ollama). Deselected by default; run with `pytest -m real_gemma`."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from tests.narrative_helpers import add_recording, make_client, svc, tone

pytestmark = pytest.mark.real_gemma


def _ollama_up() -> bool:
    try:
        return httpx.get("http://127.0.0.1:11434/api/tags", timeout=2).status_code == 200
    except httpx.HTTPError:
        return False


@pytest.mark.skipif(not _ollama_up(), reason="Ollama is not running")
def test_real_gemma_narrates_a_grounded_line(tmp_path: Path) -> None:
    c = make_client(tmp_path)  # real OllamaBackend, no fake
    try:
        status = c.get("/api/narrative/model-status").json()
        if not status.get("available"):
            pytest.skip(f"no Gemma model installed: {status}")
        add_recording(c, tone(440.0, 1))
        c.get(
            "/api/narrative/current"
        )  # queues generation; the test runs the worker step synchronously
        svc(c).narrative.run_pending()
        resp = c.get("/api/narrative/current")
        assert resp.status_code == 200, resp.text
        cur = resp.json()["utterance"]
        assert cur["lines"], cur
        # whichever source served it, the line passed the same validator the game applies
        gen = cur["generation"]
        assert gen["status"] in ("ready", "fallback"), cur
        if cur["source"] == "gemma":
            assert cur["model"] and gen["fallback_reason"] is None
        else:
            assert gen["fallback_reason"]
        assert 1 <= len(cur["lines"]) <= 3
    finally:
        c.__exit__(None, None, None)
