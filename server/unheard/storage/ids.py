"""UUIDv7 identifiers (time-ordered, opaque; never derived from paths or filenames)."""

from __future__ import annotations

import os
import re
import threading
import time
import uuid

_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


_lock = threading.Lock()
_last_ms = 0
_seq = 0


def uuid7() -> str:
    """UUIDv7 with a 12-bit per-millisecond sequence so ids created in the same
    millisecond still sort in creation order (monotonic within a process)."""
    global _last_ms, _seq
    with _lock:
        ms = int(time.time() * 1000)
        if ms <= _last_ms:
            ms = _last_ms
            _seq += 1
            if _seq >= 0x1000:  # sequence exhausted: borrow the next millisecond
                ms += 1
                _seq = 0
        else:
            _seq = 0
        _last_ms = ms
        seq = _seq
    rand = os.urandom(8)
    arr = bytearray(ms.to_bytes(6, "big") + seq.to_bytes(2, "big") + rand)
    arr[6] = (arr[6] & 0x0F) | 0x70  # version 7 (high nibble), sequence in the low 12 bits
    arr[8] = (arr[8] & 0x3F) | 0x80  # variant
    return str(uuid.UUID(bytes=bytes(arr)))


def is_valid_id(value: str) -> bool:
    return bool(_UUID_RE.match(value))
