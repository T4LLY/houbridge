from __future__ import annotations

import re
import sqlite3
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass

from houbridge.errors import BridgeError
from houbridge.search.sqlite_filter import append_membership_filter, quote_identifier


ConnectionFactory = Callable[[], AbstractContextManager[sqlite3.Connection]]


@dataclass(frozen=True)
class LexicalIndexSchema:
    """Caller-selected names for one feature's lexical state in its own DB."""

    entry_table: str
    fts_table: str

    def __post_init__(self) -> None:
        quote_identifier(self.entry_table)
        quote_identifier(self.fts_table)


@dataclass(frozen=True)
class LexicalDocument:
    entry_id: str
    namespace: str
    content: str


class SQLiteFtsIndex:
    """Contentless FTS5/BM25 primitive over a caller-owned SQLite database."""

    def __init__(self, connection_factory: ConnectionFactory, *, schema: LexicalIndexSchema) -> None:
        self._connection_factory = connection_factory
        self._schema = schema
        self._entries = quote_identifier(schema.entry_table)
        self._fts = quote_identifier(schema.fts_table)
        self._initialize()

    def _initialize(self) -> None:
        with self._connection_factory() as connection:
            connection.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self._entries}(
                    fts_id INTEGER PRIMARY KEY,
                    entry_id TEXT NOT NULL UNIQUE,
                    namespace TEXT NOT NULL
                )
                """
            )
            connection.execute(
                f"CREATE INDEX IF NOT EXISTS "
                f"{quote_identifier(self._schema.entry_table + '_namespace_lookup')} "
                f"ON {self._entries}(namespace)"
            )
            connection.execute(
                f"""
                CREATE VIRTUAL TABLE IF NOT EXISTS {self._fts} USING fts5(
                    content,
                    content = '',
                    contentless_delete = 1,
                    tokenize = "unicode61 tokenchars '_:'"
                )
                """
            )

    def upsert(self, documents: Sequence[LexicalDocument]) -> None:
        if not documents:
            return
        with self._connection_factory() as connection:
            for document in documents:
                existing = connection.execute(
                    f"SELECT fts_id FROM {self._entries} WHERE entry_id = ?",
                    (document.entry_id,),
                ).fetchone()
                if existing is not None:
                    connection.execute(
                        f"DELETE FROM {self._fts} WHERE rowid = ?",
                        (int(existing["fts_id"]),),
                    )
                connection.execute(
                    f"""
                    INSERT INTO {self._entries}(entry_id, namespace)
                    VALUES (?, ?)
                    ON CONFLICT(entry_id) DO UPDATE SET
                        namespace = excluded.namespace
                    """,
                    (document.entry_id, document.namespace),
                )
                row = connection.execute(
                    f"SELECT fts_id FROM {self._entries} WHERE entry_id = ?",
                    (document.entry_id,),
                ).fetchone()
                connection.execute(
                    f"INSERT INTO {self._fts}(rowid, content) VALUES (?, ?)",
                    (int(row["fts_id"]), document.content),
                )

    def remove(self, entry_ids: Sequence[str]) -> None:
        if not entry_ids:
            return
        with self._connection_factory() as connection:
            for entry_id in entry_ids:
                row = connection.execute(
                    f"SELECT fts_id FROM {self._entries} WHERE entry_id = ?",
                    (entry_id,),
                ).fetchone()
                if row is not None:
                    connection.execute(
                        f"DELETE FROM {self._fts} WHERE rowid = ?",
                        (int(row["fts_id"]),),
                    )
                connection.execute(
                    f"DELETE FROM {self._entries} WHERE entry_id = ?",
                    (entry_id,),
                )

    def search(
        self,
        query: str,
        *,
        namespaces: Sequence[str],
        limit: int,
        entry_ids: Sequence[str] | None = None,
    ) -> list[str]:
        if not query.strip() or not namespaces or limit <= 0:
            return []

        placeholders = ",".join("?" for _ in namespaces)
        try:
            with self._connection_factory() as connection:
                where = [
                    f"{self._fts} MATCH ?",
                    f'e."namespace" IN ({placeholders})',
                ]
                params: list[object] = [_fts_query(query), *namespaces]
                append_membership_filter(
                    connection,
                    where,
                    params,
                    column="e.entry_id",
                    values=entry_ids,
                    temp_table="houbridge_fts_entry_filter",
                )
                params.append(limit)
                rows = connection.execute(
                    f"""
                    SELECT e.entry_id, bm25({self._fts}) AS score
                    FROM {self._fts}
                    JOIN {self._entries} e ON e.fts_id = {self._fts}.rowid
                    WHERE {' AND '.join(where)}
                    ORDER BY score ASC
                    LIMIT ?
                    """,
                    tuple(params),
                ).fetchall()
        except sqlite3.OperationalError as exc:
            raise BridgeError(
                "lexical_search_failed",
                "SQLite FTS search failed.",
                detail=str(exc),
            ) from exc
        return [str(row["entry_id"]) for row in rows]


def _fts_query(query: str) -> str:
    terms = re.findall(r"[\w:]+", query, flags=re.UNICODE)
    if not terms:
        return '"' + query.replace('"', '""') + '"'
    return " OR ".join('"' + term.replace('"', '""') + '"' for term in terms)
