from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from houbridge.db.connection import connect, connection_scope


def test_connect_applies_shared_sqlite_pragmas(tmp_path: Path) -> None:
    connection = connect(tmp_path / "nested" / "state.db")
    try:
        assert connection.row_factory is sqlite3.Row
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert connection.execute("PRAGMA synchronous").fetchone()[0] == 1
    finally:
        connection.close()


def test_connect_applies_explicit_busy_timeout(tmp_path: Path) -> None:
    connection = connect(tmp_path / "busy.db", busy_timeout_seconds=12.5)
    try:
        assert connection.execute("PRAGMA busy_timeout").fetchone()[0] == 12_500
    finally:
        connection.close()


def test_connection_scope_commits_on_success(tmp_path: Path) -> None:
    database = tmp_path / "state.db"
    with connection_scope(database) as connection:
        connection.execute("CREATE TABLE example (value TEXT NOT NULL)")
        connection.execute("INSERT INTO example(value) VALUES (?)", ("ok",))

    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT value FROM example").fetchone() == ("ok",)


def test_connection_scope_rolls_back_on_failure(tmp_path: Path) -> None:
    database = tmp_path / "state.db"
    with connection_scope(database) as connection:
        connection.execute("CREATE TABLE example (value TEXT NOT NULL)")

    with pytest.raises(RuntimeError, match="boom"):
        with connection_scope(database) as connection:
            connection.execute("INSERT INTO example(value) VALUES (?)", ("no",))
            raise RuntimeError("boom")

    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM example").fetchone() == (0,)
