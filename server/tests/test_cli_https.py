"""`unheard serve` passes TLS options to uvicorn and refuses half a certificate pair."""

from __future__ import annotations

from typing import Any

import pytest

from unheard.cli import main


def test_tls_options_reach_uvicorn(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}
    import uvicorn

    monkeypatch.setattr(uvicorn, "run", lambda *a, **kw: seen.update(kw))
    assert main(["serve", "--ssl-certfile", "c.pem", "--ssl-keyfile", "k.pem"]) == 0
    assert seen["ssl_certfile"] == "c.pem" and seen["ssl_keyfile"] == "k.pem"
    assert seen["host"] in ("127.0.0.1", "localhost")  # TLS does not widen the bind address


def test_plain_http_remains_the_default(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}
    import uvicorn

    monkeypatch.setattr(uvicorn, "run", lambda *a, **kw: seen.update(kw))
    assert main(["serve"]) == 0
    assert seen["ssl_certfile"] is None and seen["ssl_keyfile"] is None


def test_half_a_certificate_pair_is_refused(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import uvicorn

    monkeypatch.setattr(uvicorn, "run", lambda *a, **kw: pytest.fail("must not start"))
    assert main(["serve", "--ssl-certfile", "c.pem"]) == 2
    assert "together" in capsys.readouterr().err
