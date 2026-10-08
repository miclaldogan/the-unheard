from __future__ import annotations

import os
import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from unheard.app import create_app
from unheard.config import Settings

HAS_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None
requires_ffmpeg = pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg/ffprobe not installed")


def make_settings(tmp_path: Path, **overrides: object) -> Settings:
    base = dict(data_dir=tmp_path / "data", worker_enabled=False, api_token=None)
    base.update(overrides)
    # Make sure a developer .env does not leak into tests
    os.environ.pop("UNHEARD_DATA_DIR", None)
    return Settings(_env_file=None, **base)  # type: ignore[call-arg]


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return make_settings(tmp_path)


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    app = create_app(settings, web_dist=Path("/nonexistent"))
    with TestClient(app) as c:
        yield c


def run_jobs(client: TestClient) -> int:
    """Drive the (disabled) worker synchronously."""
    return int(client.app.state.services.worker.run_pending())  # type: ignore[attr-defined]
