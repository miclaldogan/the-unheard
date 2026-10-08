from __future__ import annotations

from pathlib import Path

import pytest

from unheard.storage.blobs import BlobStore
from unheard.storage.ids import is_valid_id, uuid7


def test_uuid7_valid_and_sortable() -> None:
    a, b = uuid7(), uuid7()
    assert is_valid_id(a) and is_valid_id(b)
    assert a <= b
    assert not is_valid_id("../etc/passwd")


def test_paths_cannot_escape(tmp_path: Path) -> None:
    store = BlobStore(tmp_path)
    rid = uuid7()
    with pytest.raises(ValueError):
        store.relative_path("audio", "../../x", "a.wav")
    with pytest.raises(ValueError):
        store.relative_path("audio", rid, "../a.wav")
    with pytest.raises(ValueError):
        store.absolute("../outside.wav")
    with pytest.raises(ValueError):
        store.relative_path("etc", rid, "a.wav")
    rel = store.relative_path("audio", rid, "source.wav")
    assert store.absolute(rel).is_relative_to(tmp_path)


def test_atomic_write_and_cleanup(tmp_path: Path) -> None:
    store = BlobStore(tmp_path)
    rid = uuid7()
    rel = store.relative_path("artifacts", rid, "f.npz")
    p = store.write_atomic(rel, b"abc")
    assert p.read_bytes() == b"abc"
    assert not list(p.parent.glob(".tmp-*"))
    store.delete_recording_dirs(rid)
    assert not p.parent.exists()
