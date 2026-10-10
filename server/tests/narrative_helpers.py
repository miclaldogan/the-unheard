"""Helpers for M5 tests: a scriptable Gemma backend and flows that drive the real app with real DSP + the test-double ears."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
from fastapi.testclient import TestClient

from tests.conftest import make_settings, run_jobs
from tests.fakes import install_fake
from tests.fixtures import synth
from unheard.app import create_app
from unheard.narrative.gemma import GemmaError, Generation

SR = 48_000


class FakeGemma:
    """Scriptable backend. `script` is called with (system, user, schema) and returns a dict (the model's JSON) or raises."""

    def __init__(
        self,
        script: Callable[[str, str, dict[str, Any]], dict[str, Any]] | None = None,
        *,
        installed: list[str] | None = None,
        delay_s: float = 0.0,
        fail_installed: bool = False,
    ) -> None:
        self.script = script or self.grounded_reply
        self._installed = ["gemma3:4b"] if installed is None else installed
        self.delay_s = delay_s
        self.fail_installed = fail_installed
        self.calls: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    def installed(self) -> list[str]:
        if self.fail_installed:
            raise GemmaError("unavailable", "connection refused")
        return list(self._installed)

    def generate(
        self, model: str, system: str, user: str, schema: dict[str, Any], *, seed: int | None = None
    ) -> Generation:
        with self._lock:
            self.calls.append({"model": model, "system": system, "user": user, "seed": seed})
        if self.delay_s:
            time.sleep(self.delay_s)
        return Generation(self.script(system, user, schema), 12.5, model)

    @staticmethod
    def grounded_reply(system: str, user: str, schema: dict[str, Any]) -> dict[str, Any]:
        """A well-behaved model: restates the first fact in its own words, citing it."""
        if "picks" in str(schema):
            return {"picks": [{"id": "M1", "text": "Bring me a sound I could not name before."}]}
        first = next(
            (ln for ln in user.splitlines() if ln.startswith("F1 ")), "F1 [system] something"
        )
        label = None
        if "'" in first:
            label = first.split("'")[1]
        text = (
            f"The ears offered '{label}', and I am still unsure of it."
            if label
            else "I kept something from this moment."
        )
        return {"lines": [{"text": text, "kind": "grounded", "cites": ["F1"]}]}


def tone(f: float, seed: int = 0, dur: float = 4.0) -> np.ndarray:
    return synth.sine(f, SR, dur, amp=0.4) + 0.01 * np.random.default_rng(seed).standard_normal(
        int(SR * dur)
    )


def noise(seed: int, dur: float = 4.0) -> np.ndarray:
    return synth.white_noise(SR, dur, amp=0.2, seed=seed)


def clicks(rate: float = 4.0, dur: float = 4.0) -> np.ndarray:
    return synth.click_train(rate, SR, dur)


def make_client(
    tmp_path: Path,
    backend: FakeGemma | None = None,
    *,
    gemma: bool = True,
    model: str = "fake/clap",
) -> TestClient:
    settings = make_settings(tmp_path, model_name=model, narrative_gemma=gemma)
    c = TestClient(create_app(settings, web_dist=Path("/nonexistent")))
    c.__enter__()
    svc = c.app.state.services  # type: ignore[attr-defined]
    if model != "none":
        install_fake(svc)
    if backend is not None:
        svc.narrative.backend = backend
        svc.narrative._avail = (0.0, None, None)
    return c


def svc(c: TestClient):  # type: ignore[no-untyped-def]
    return c.app.state.services  # type: ignore[attr-defined]


def add_recording(c: TestClient, x: np.ndarray, name: str = "clip.wav") -> str:
    r = c.post("/api/recordings", files={"file": (name, synth.wav_bytes(x, SR), "audio/wav")})
    assert r.status_code == 202, r.text
    rid = str(r.json()["recording_id"])
    run_jobs(c)
    return rid


def teach(
    c: TestClient, rid: str, name: str | None = None, label_id: str | None = None, **extra: Any
) -> dict[str, Any]:
    body: dict[str, Any] = {**extra}
    if name:
        body["new_labels"] = [name]
    elif label_id:
        body["label_ids"] = [label_id]
    r = c.post(f"/api/recordings/{rid}/annotations", json=body)
    assert r.status_code == 201, r.text
    return r.json()  # type: ignore[no-any-return]


def compose_ready(c: TestClient, ids: list[str], **kw: Any) -> str:
    r = c.post("/api/compositions", json={"recording_ids": ids, "duration_s": 20, **kw})
    assert r.status_code in (200, 202), r.text
    svc(c).compositions.run_pending()
    assert c.get(f"/api/compositions/{r.json()['id']}").json()["status"] == "ready"
    return str(r.json()["id"])


def narrate(c: TestClient) -> dict[str, Any]:
    """current() then let the (disabled) worker finish any pending generation."""
    c.get("/api/narrative/current")
    svc(c).narrative.run_pending()
    return c.get("/api/narrative/current").json()  # type: ignore[no-any-return]
