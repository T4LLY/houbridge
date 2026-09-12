from __future__ import annotations

from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
import sqlite3

from houbridge.search.sqlite_filter import quote_identifier


ConnectionFactory = Callable[[], AbstractContextManager[sqlite3.Connection]]


@dataclass(frozen=True, slots=True)
class IndexedScript:
    entry_id: str
    relative_path: str
    public_path: str
    content_hash: str
    semantic_hash: str
    description: str | None
    embedding_profile: str


class ScriptIndexRepository:
    """File-level Script Search metadata in the workspace-derived database."""

    def __init__(
        self,
        connection_factory: ConnectionFactory,
        *,
        table_name: str = "script_entries",
    ) -> None:
        self._connect = connection_factory
        self._table = quote_identifier(table_name)
        self._initialize()

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self._table}(
                    entry_id TEXT PRIMARY KEY,
                    relative_path TEXT NOT NULL UNIQUE,
                    public_path TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    semantic_hash TEXT NOT NULL,
                    description TEXT,
                    embedding_profile_id TEXT NOT NULL
                ) WITHOUT ROWID
                """
            )

    def all(self) -> dict[str, IndexedScript]:
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT entry_id, relative_path, public_path, content_hash,
                       semantic_hash, description, embedding_profile_id
                FROM {self._table}
                """
            ).fetchall()
        return {
            str(row["relative_path"]): _row_to_indexed(row)
            for row in rows
        }

    def by_entry_ids(self, entry_ids: Sequence[str]) -> dict[str, IndexedScript]:
        if not entry_ids:
            return {}
        placeholders = ",".join("?" for _ in entry_ids)
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT entry_id, relative_path, public_path, content_hash,
                       semantic_hash, description, embedding_profile_id
                FROM {self._table}
                WHERE entry_id IN ({placeholders})
                """,
                tuple(entry_ids),
            ).fetchall()
        return {str(row["entry_id"]): _row_to_indexed(row) for row in rows}

    def replace(self, entries: Sequence[IndexedScript]) -> None:
        if not entries:
            return
        with self._connect() as connection:
            connection.executemany(
                f"""
                INSERT INTO {self._table}(
                    entry_id, relative_path, public_path, content_hash,
                    semantic_hash, description, embedding_profile_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(entry_id) DO UPDATE SET
                    relative_path = excluded.relative_path,
                    public_path = excluded.public_path,
                    content_hash = excluded.content_hash,
                    semantic_hash = excluded.semantic_hash,
                    description = excluded.description,
                    embedding_profile_id = excluded.embedding_profile_id
                """,
                [
                    (
                        entry.entry_id,
                        entry.relative_path,
                        entry.public_path,
                        entry.content_hash,
                        entry.semantic_hash,
                        entry.description,
                        entry.embedding_profile,
                    )
                    for entry in entries
                ],
            )

    def remove(self, entry_ids: Sequence[str]) -> None:
        if not entry_ids:
            return
        with self._connect() as connection:
            connection.executemany(
                f"DELETE FROM {self._table} WHERE entry_id = ?",
                [(entry_id,) for entry_id in entry_ids],
            )


def _row_to_indexed(row: sqlite3.Row) -> IndexedScript:
    return IndexedScript(
        entry_id=str(row["entry_id"]),
        relative_path=str(row["relative_path"]),
        public_path=str(row["public_path"]),
        content_hash=str(row["content_hash"]),
        semantic_hash=str(row["semantic_hash"]),
        description=(str(row["description"]) if row["description"] is not None else None),
        embedding_profile=str(row["embedding_profile_id"]),
    )
