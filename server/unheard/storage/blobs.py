"""Filesystem blob store with safe, generated paths and atomic writes.

Paths are derived from the recording id (a UUID validated by ``is_valid_id``), never from
client-supplied names, and are always resolved inside ``data_dir``.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from unheard.storage.ids import is_valid_id


class BlobStore:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def relative_path(self, category: str, recording_id: str, filename: str) -> str:
        if not is_valid_id(recording_id):
            raise ValueError("invalid recording id")
        if category not in {"audio", "artifacts"}:
            raise ValueError("invalid category")
        if "/" in filename or "\\" in filename or filename in {"", ".", ".."}:
            raise ValueError("invalid filename")
        # Shard by the first two hex chars to keep directories small.
        return f"{category}/{recording_id[:2]}/{recording_id}/{filename}"

    def absolute(self, relative: str) -> Path:
        candidate = (self.root / relative).resolve()
        if self.root not in candidate.parents:
            raise ValueError("path escapes data directory")
        return candidate

    def write_atomic(self, relative: str, data: bytes) -> Path:
        target = self.absolute(relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=target.parent)
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, target)
        except BaseException:
            try:
                os.unlink(tmp)
            except FileNotFoundError:
                pass
            raise
        return target

    def delete(self, relative: str) -> None:
        try:
            self.absolute(relative).unlink()
        except FileNotFoundError:
            pass

    def composition_path(self, composition_id: str, filename: str) -> str:
        """``compositions/<aa>/<id>/<filename>`` (filename may be ``stems/<name>``)."""
        if not is_valid_id(composition_id):
            raise ValueError("invalid composition id")
        parts = filename.split("/")
        if len(parts) > 2 or any(p in {"", ".", ".."} or "\\" in p for p in parts):
            raise ValueError("invalid filename")
        return f"compositions/{composition_id[:2]}/{composition_id}/{filename}"

    def delete_composition_dir(self, composition_id: str) -> None:
        if not is_valid_id(composition_id):
            raise ValueError("invalid composition id")
        d = self.absolute(f"compositions/{composition_id[:2]}/{composition_id}")
        if d.is_dir():
            import shutil

            shutil.rmtree(d)

    def delete_recording_dirs(self, recording_id: str) -> None:
        """Remove every file under audio/ and artifacts/ for a recording."""
        if not is_valid_id(recording_id):
            raise ValueError("invalid recording id")
        for category in ("audio", "artifacts"):
            d = self.absolute(f"{category}/{recording_id[:2]}/{recording_id}")
            if d.is_dir():
                for p in d.iterdir():
                    p.unlink()
                d.rmdir()
