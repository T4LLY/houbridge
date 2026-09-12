from __future__ import annotations

import hashlib
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from houbridge.db.connection import connection_scope
from houbridge.process_coordination import InterprocessFileLock, coordination_directory


class HistoryDatabaseMissingError(FileNotFoundError):
    """Raised when a non-creating History operation loses its database."""


def history_database_lock_path(database: Path) -> Path:
    """Return the fixed-runtime coordination lock for one History database."""

    canonical = str(database.expanduser().resolve()).encode("utf-8")
    digest = hashlib.sha256(canonical).hexdigest()
    return coordination_directory() / "history-database" / f"{digest}.lock"


@contextmanager
def history_connection_scope(
    database: Path,
    *,
    require_existing: bool = False,
) -> Iterator[sqlite3.Connection]:
    """Keep scene-reset deletion outside the lifetime of a SQLite connection."""

    resolved = database.expanduser().resolve()
    lock = InterprocessFileLock()
    with lock.acquire(history_database_lock_path(resolved)):
        if require_existing and not resolved.is_file():
            raise HistoryDatabaseMissingError(str(resolved))
        with connection_scope(resolved) as connection:
            yield connection
