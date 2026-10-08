"""SQLite connection management and numbered SQL migrations (``PRAGMA user_version``)."""

from __future__ import annotations

import logging
import re
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

log = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
_MIGRATION_RE = re.compile(r"^(\d{4})_[a-z0-9_]+\.sql$")


def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA secure_delete=ON")
    conn.execute("PRAGMA busy_timeout=10000")
    return conn


def migrate(conn: sqlite3.Connection) -> int:
    """Apply pending migrations in order. Returns the resulting schema version."""
    current = int(conn.execute("PRAGMA user_version").fetchone()[0])
    files = sorted(p for p in MIGRATIONS_DIR.iterdir() if _MIGRATION_RE.match(p.name))
    for path in files:
        version = int(path.name[:4])
        if version <= current:
            continue
        sql = path.read_text(encoding="utf-8")
        # executescript() commits any pending transaction first, so the transaction has
        # to live inside the script itself for the migration to be atomic.
        try:
            conn.executescript(f"BEGIN;\n{sql}\nPRAGMA user_version={version};\nCOMMIT;")
        except Exception:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        log.info("applied migration %s", path.name)
        current = version
    return current


class Database:
    """A small thread-safe wrapper: one connection guarded by a lock.

    SQLite serialises writers anyway; a single connection with a lock keeps the
    worker thread and request handlers from interleaving half-finished transactions.
    """

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._conn = _connect(path)
        self._lock = threading.RLock()
        self.schema_version = migrate(self._conn)

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            yield self._conn

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """``BEGIN IMMEDIATE`` ... ``COMMIT``/``ROLLBACK`` around the block."""
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self._conn
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            else:
                self._conn.execute("COMMIT")

    def close(self) -> None:
        with self._lock:
            self._conn.close()
