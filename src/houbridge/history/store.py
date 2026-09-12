from __future__ import annotations

import hashlib
import sqlite3
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np

from houbridge.db.connection import connection_scope
from houbridge.errors import BridgeError
from houbridge.search.embedding import (
    EmbeddingCoordinator,
    EmbeddingItem,
    EmbeddingProvider,
    Model2VecEmbeddingProvider,
    SQLiteEmbeddingCache,
)
from houbridge.search.lexical import LexicalIndexSchema, SQLiteFtsIndex

from .schema import initialize_history_schema


ConnectionFactory = Callable[[], AbstractContextManager[sqlite3.Connection]]
_CODE_PROFILE_KEY = "code_embedding_profile"
_SOURCE_EMBEDDING_TABLE = "history_source_embeddings"
_LEXICAL_SCHEMA = LexicalIndexSchema(
    entry_table="history_lexical_entries",
    fts_table="history_lexical_fts",
)


@dataclass(frozen=True, slots=True)
class HistorySourceEmbedding:
    source_hash: str
    profile: str
    vector: np.ndarray


class HistoryStore:
    """Persistence owned by one exact Houdini process-incarnation History."""

    def __init__(
        self,
        database: Path,
        *,
        embedding_provider: EmbeddingProvider | None = None,
    ) -> None:
        self.database = database
        self._provider = embedding_provider or Model2VecEmbeddingProvider()

    def exists(self) -> bool:
        return self.database.is_file()

    def initialize(self, requested_code_profile: str) -> str:
        requested = requested_code_profile.strip()
        if not requested:
            raise ValueError("History code embedding profile must not be empty")

        with self._connect() as connection:
            initialize_history_schema(connection)
            connection.execute(
                """
                INSERT INTO history_metadata(key, value)
                VALUES (?, ?)
                ON CONFLICT(key) DO NOTHING
                """,
                (_CODE_PROFILE_KEY, requested),
            )
            row = connection.execute(
                "SELECT value FROM history_metadata WHERE key = ?",
                (_CODE_PROFILE_KEY,),
            ).fetchone()
        if row is None:
            raise BridgeError(
                "history_store_invalid",
                "History database is missing its code embedding profile.",
            )
        profile = str(row["value"])
        if not profile.strip():
            raise BridgeError(
                "history_store_invalid",
                "History database contains an empty code embedding profile.",
            )

        # These are History-owned derived search structures. They live in the
        # same session database and never make workspace search.db authoritative.
        SQLiteEmbeddingCache(self._connect, table_name=_SOURCE_EMBEDDING_TABLE)
        SQLiteFtsIndex(self._connect, schema=_LEXICAL_SCHEMA)
        return profile

    def code_profile(self) -> str | None:
        if not self.exists():
            return None
        with self._connect() as connection:
            try:
                row = connection.execute(
                    "SELECT value FROM history_metadata WHERE key = ?",
                    (_CODE_PROFILE_KEY,),
                ).fetchone()
            except sqlite3.OperationalError:
                return None
        return None if row is None else str(row["value"])

    def allocate_id(self, *, requested_code_profile: str) -> int:
        self.initialize(requested_code_profile)
        with self._connect() as connection:
            row = connection.execute(
                """
                UPDATE history_id_sequence
                SET next_id = next_id + 1
                WHERE singleton = 1
                RETURNING next_id - 1 AS allocated_id
                """
            ).fetchone()
        if row is None:
            raise BridgeError(
                "history_store_invalid",
                "History database is missing its id allocator.",
            )
        return int(row["allocated_id"])

    def embed_source(
        self,
        source: str,
        *,
        requested_code_profile: str,
    ) -> HistorySourceEmbedding:
        profile = self.initialize(requested_code_profile)
        source_hash = hashlib.sha256(source.encode("utf-8")).hexdigest()
        cache = SQLiteEmbeddingCache(self._connect, table_name=_SOURCE_EMBEDDING_TABLE)
        vector = EmbeddingCoordinator(self._provider, cache).encode(
            [EmbeddingItem(content_hash=source_hash, text=source)],
            profile=profile,
        )[source_hash]
        return HistorySourceEmbedding(
            source_hash=source_hash,
            profile=profile,
            vector=vector.copy(),
        )

    def _connect(self) -> AbstractContextManager[sqlite3.Connection]:
        return connection_scope(self.database)
