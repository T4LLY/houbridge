from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np

from houbridge.history.locking import (
    HistoryDatabaseMissingError,
    history_connection_scope,
)
from houbridge.errors import BridgeError
from houbridge.search.embedding import (
    EmbeddingCoordinator,
    EmbeddingItem,
    EmbeddingProvider,
    Model2VecEmbeddingProvider,
    SQLiteEmbeddingCache,
)
from houbridge.search.dense import SQLiteVecIndex
from houbridge.search.lexical import SQLiteFtsIndex

from .changes import ActionChange
from .schema import initialize_history_schema
from .search_schema import DENSE_SCHEMA, LEXICAL_SCHEMA, SOURCE_EMBEDDING_TABLE


ConnectionFactory = Callable[[], AbstractContextManager[sqlite3.Connection]]
_CODE_PROFILE_KEY = "code_embedding_profile"



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
        lock_timeout_seconds: float = 120.0,
    ) -> None:
        self.database = database
        self._provider = embedding_provider or Model2VecEmbeddingProvider()
        self.lock_timeout_seconds = float(lock_timeout_seconds)

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
        SQLiteEmbeddingCache(self._connect_existing, table_name=SOURCE_EMBEDDING_TABLE)
        SQLiteVecIndex(self._connect_existing, schema=DENSE_SCHEMA)
        SQLiteFtsIndex(self._connect_existing, schema=LEXICAL_SCHEMA)
        return profile

    def code_profile(self) -> str | None:
        if not self.exists():
            return None
        try:
            with self._connect_existing() as connection:
                try:
                    row = connection.execute(
                        "SELECT value FROM history_metadata WHERE key = ?",
                        (_CODE_PROFILE_KEY,),
                    ).fetchone()
                except sqlite3.OperationalError:
                    return None
        except HistoryDatabaseMissingError:
            return None
        return None if row is None else str(row["value"])

    def allocate_id(self, *, requested_code_profile: str) -> int:
        self.initialize(requested_code_profile)
        with self._connect_existing() as connection:
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
        cache = SQLiteEmbeddingCache(self._connect_existing, table_name=SOURCE_EMBEDDING_TABLE)
        vector = EmbeddingCoordinator(self._provider, cache).encode(
            [EmbeddingItem(content_hash=source_hash, text=source)],
            profile=profile,
        )[source_hash]
        return HistorySourceEmbedding(
            source_hash=source_hash,
            profile=profile,
            vector=vector.copy(),
        )

    def commit_entry(
        self,
        *,
        expected_code_profile: str,
        time: str,
        cwd: str,
        status: str,
        file: str,
        args: tuple[str, ...],
        purpose: str | None,
        source_hash: str,
        changes: tuple[ActionChange, ...],
        execution_key: str | None = None,
    ) -> int:
        """Commit one finalized started action without recreating missing History."""

        if status not in {"completed", "failed"}:
            raise ValueError("History status must be completed or failed")
        if not self.exists():
            raise BridgeError(
                "history_finalize_failed",
                "History database disappeared before action finalization.",
            )

        with self._connect_existing() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if execution_key is not None:
                normalized_key = execution_key.strip()
                if not normalized_key:
                    raise ValueError("History execution key must not be empty")
                existing = connection.execute(
                    "SELECT entry_id FROM history_execution_keys WHERE execution_key = ?",
                    (normalized_key,),
                ).fetchone()
                if existing is not None:
                    return int(existing["entry_id"])
            else:
                normalized_key = None

            profile_row = connection.execute(
                "SELECT value FROM history_metadata WHERE key = ?",
                (_CODE_PROFILE_KEY,),
            ).fetchone()
            if profile_row is None or str(profile_row["value"]) != expected_code_profile:
                raise BridgeError(
                    "history_finalize_failed",
                    "History embedding profile changed before action finalization.",
                )
            embedding_row = connection.execute(
                f"""
                SELECT 1
                FROM {SOURCE_EMBEDDING_TABLE}
                WHERE embedding_profile_id = ? AND content_hash = ?
                """,
                (expected_code_profile, source_hash),
            ).fetchone()
            if embedding_row is None:
                raise BridgeError(
                    "history_finalize_failed",
                    "History source embedding is missing at action finalization.",
                )

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
            entry_id = int(row["allocated_id"])
            connection.execute(
                """
                INSERT INTO history_entries(
                    id, time, cwd, status, file, args_json, purpose, source_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry_id,
                    time,
                    cwd,
                    status,
                    file,
                    json.dumps(list(args), ensure_ascii=False, separators=(",", ":")),
                    purpose,
                    source_hash,
                ),
            )
            for ordinal, change in enumerate(changes):
                connection.execute(
                    """
                    INSERT INTO history_changes(
                        entry_id, ordinal, node_session_id, payload_json
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (
                        entry_id,
                        ordinal,
                        int(change.node),
                        json.dumps(
                            change.to_payload(),
                            ensure_ascii=False,
                            separators=(",", ":"),
                            sort_keys=True,
                        ),
                    ),
                )
            if normalized_key is not None:
                connection.execute(
                    "INSERT INTO history_execution_keys(execution_key, entry_id) VALUES (?, ?)",
                    (normalized_key, entry_id),
                )
        return entry_id

    def _connect(self) -> AbstractContextManager[sqlite3.Connection]:
        return history_connection_scope(
            self.database,
            lock_timeout_seconds=self.lock_timeout_seconds,
        )

    def _connect_existing(self) -> AbstractContextManager[sqlite3.Connection]:
        return history_connection_scope(
            self.database,
            require_existing=True,
            lock_timeout_seconds=self.lock_timeout_seconds,
        )
