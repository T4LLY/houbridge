from __future__ import annotations

import hashlib
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from houbridge.db.connection import connection_scope
from houbridge.errors import BridgeError
from houbridge.process_coordination import (
    InterprocessFileLock,
    InterprocessFileLockTimeout,
    coordination_directory,
)


class HistoryDatabaseMissingError(FileNotFoundError):
    """Raised when a non-creating History operation loses its database."""


_DEFAULT_HISTORY_LOCK_TIMEOUT_SECONDS = 120.0


def history_database_lock_path(database: Path) -> Path:
    """Return the fixed-runtime coordination lock for one History database."""

    canonical = str(database.expanduser().resolve()).encode("utf-8")
    digest = hashlib.sha256(canonical).hexdigest()
    return coordination_directory() / "history-database" / f"{digest}.lock"


def history_database_reset_path(database: Path) -> Path:
    """Return the pending scene-reset marker for one History database."""

    return history_database_lock_path(database).with_suffix(".reset")


@contextmanager
def history_connection_scope(
    database: Path,
    *,
    require_existing: bool = False,
    lock_timeout_seconds: float = _DEFAULT_HISTORY_LOCK_TIMEOUT_SECONDS,
) -> Iterator[sqlite3.Connection]:
    """Keep scene-reset deletion outside the lifetime of a SQLite connection."""

    resolved = database.expanduser().resolve()
    lock = InterprocessFileLock()
    try:
        with lock.acquire(
            history_database_lock_path(resolved),
            timeout_seconds=lock_timeout_seconds,
        ):
            _apply_pending_scene_reset(resolved)
            if require_existing and not resolved.is_file():
                raise HistoryDatabaseMissingError(str(resolved))
            with connection_scope(
                resolved,
                busy_timeout_seconds=lock_timeout_seconds,
            ) as connection:
                yield connection
    except InterprocessFileLockTimeout as exc:
        raise BridgeError(
            "history_lock_timeout",
            "Timed out waiting for the History database lock.",
            str(resolved),
        ) from exc


def _apply_pending_scene_reset(database: Path) -> None:
    marker = history_database_reset_path(database)
    if not marker.is_file():
        return
    for path in _history_database_files(database):
        try:
            path.unlink()
        except FileNotFoundError:
            pass
    try:
        marker.unlink()
    except FileNotFoundError:
        pass


def _history_database_files(database: Path) -> tuple[Path, ...]:
    return (
        database,
        Path(str(database) + "-wal"),
        Path(str(database) + "-shm"),
        Path(str(database) + "-journal"),
    )
