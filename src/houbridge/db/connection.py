from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


def connect(path: Path, *, auto_vacuum_incremental: bool = False) -> sqlite3.Connection:
    """Open one Houbridge SQLite database with shared low-level pragmas."""

    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    if auto_vacuum_incremental:
        connection.execute("PRAGMA auto_vacuum = INCREMENTAL")
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA synchronous = NORMAL")
    return connection


@contextmanager
def connection_scope(
    path: Path,
    *,
    auto_vacuum_incremental: bool = False,
) -> Iterator[sqlite3.Connection]:
    """Commit on success, roll back on failure, and always close the connection."""

    connection = connect(path, auto_vacuum_incremental=auto_vacuum_incremental)
    try:
        with connection:
            yield connection
    finally:
        connection.close()
