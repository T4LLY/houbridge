from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass

import numpy as np

from houbridge.errors import BridgeError
from houbridge.search.sqlite_filter import append_membership_filter, quote_identifier


ConnectionFactory = Callable[[], AbstractContextManager[sqlite3.Connection]]


@dataclass(frozen=True)
class DenseIndexSchema:
    """Caller-selected names for one feature's dense storage in its own DB."""

    profile_table: str
    vector_table_prefix: str

    def __post_init__(self) -> None:
        quote_identifier(self.profile_table)
        quote_identifier(self.vector_table_prefix)

    def vector_table_name(self, profile: str) -> str:
        digest = hashlib.sha256(profile.encode("utf-8")).hexdigest()[:16]
        return f"{self.vector_table_prefix}_{digest}"


@dataclass(frozen=True)
class DenseVectorRecord:
    entry_id: str
    namespace: str
    vector: np.ndarray


class SQLiteVecIndex:
    """sqlite-vec cosine primitive over a caller-owned connection and schema names."""

    def __init__(self, connection_factory: ConnectionFactory, *, schema: DenseIndexSchema) -> None:
        self._connection_factory = connection_factory
        self._schema = schema
        self._initialize_profile_registry()

    def _connect(self) -> AbstractContextManager[sqlite3.Connection]:
        return self._connection_factory()

    def _initialize_profile_registry(self) -> None:
        profile_table = quote_identifier(self._schema.profile_table)
        with self._connect() as connection:
            connection.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {profile_table}(
                    embedding_profile_id TEXT PRIMARY KEY,
                    dimensions INTEGER NOT NULL,
                    vector_table_name TEXT NOT NULL UNIQUE
                ) WITHOUT ROWID
                """
            )

    def upsert(self, profile: str, records: Sequence[DenseVectorRecord]) -> None:
        if not records:
            return
        normalized = [
            (record, np.asarray(record.vector, dtype=np.float32).reshape(-1))
            for record in records
        ]
        dimensions = int(normalized[0][1].size)
        if dimensions <= 0:
            raise ValueError("embedding vector must not be empty")
        if any(vector.size != dimensions for _, vector in normalized):
            raise BridgeError(
                "embedding_dimension_mismatch",
                f"Embedding dimensions changed within profile: {profile}",
            )

        table_name = self._ensure_profile(profile, dimensions)
        quoted_table = quote_identifier(table_name)
        with self._connect() as connection:
            load_sqlite_vec(connection)
            connection.executemany(
                f"DELETE FROM {quoted_table} WHERE entry_id = ?",
                [(record.entry_id,) for record, _ in normalized],
            )
            connection.executemany(
                f"""
                INSERT INTO {quoted_table}(entry_id, embedding, namespace)
                VALUES (?, ?, ?)
                """,
                [
                    (record.entry_id, _serialize(vector), record.namespace)
                    for record, vector in normalized
                ],
            )

    def remove(self, profile: str, entry_ids: Sequence[str]) -> None:
        if not entry_ids:
            return
        table_name = self._table_for_profile(profile)
        quoted_table = quote_identifier(table_name)
        with self._connect() as connection:
            load_sqlite_vec(connection)
            connection.executemany(
                f"DELETE FROM {quoted_table} WHERE entry_id = ?",
                [(entry_id,) for entry_id in entry_ids],
            )

    def search_scored(
        self,
        profile: str,
        query_vector: np.ndarray,
        *,
        namespaces: Sequence[str],
        top_k: int,
        entry_ids: Sequence[str] | None = None,
    ) -> list[tuple[str, float]]:
        if top_k <= 0 or not namespaces:
            return []
        query = np.asarray(query_vector, dtype=np.float32).reshape(-1)
        if query.size == 0:
            raise ValueError("query vector must not be empty")

        table_name = self._table_for_profile(profile)
        quoted_table = quote_identifier(table_name)
        try:
            with self._connect() as connection:
                load_sqlite_vec(connection)
                where = ["embedding MATCH ?", "k = ?"]
                params: list[object] = [_serialize(query), top_k]
                placeholders = ",".join("?" for _ in namespaces)
                where.append(f"namespace IN ({placeholders})")
                params.extend(namespaces)
                append_membership_filter(
                    connection,
                    where,
                    params,
                    column="entry_id",
                    values=entry_ids,
                    temp_table="houbridge_dense_entry_filter",
                )
                rows = connection.execute(
                    f"""
                    SELECT entry_id, distance
                    FROM {quoted_table}
                    WHERE {' AND '.join(where)}
                    ORDER BY distance
                    """,
                    tuple(params),
                ).fetchall()
        except sqlite3.Error as exc:
            raise BridgeError(
                "dense_search_failed",
                "sqlite-vec dense search failed.",
                detail=str(exc),
            ) from exc
        return [(str(row["entry_id"]), 1.0 - float(row["distance"])) for row in rows]

    def search(
        self,
        profile: str,
        query_vector: np.ndarray,
        *,
        namespaces: Sequence[str],
        top_k: int,
        entry_ids: Sequence[str] | None = None,
    ) -> list[str]:
        return [
            entry_id
            for entry_id, _ in self.search_scored(
                profile,
                query_vector,
                namespaces=namespaces,
                top_k=top_k,
                entry_ids=entry_ids,
            )
        ]

    def _ensure_profile(self, profile: str, dimensions: int) -> str:
        if not profile.strip():
            raise ValueError("embedding profile must not be empty")
        profile_table = quote_identifier(self._schema.profile_table)
        table_name = self._schema.vector_table_name(profile)
        quoted_vector_table = quote_identifier(table_name)
        with self._connect() as connection:
            load_sqlite_vec(connection)
            row = connection.execute(
                f"""
                SELECT dimensions, vector_table_name
                FROM {profile_table}
                WHERE embedding_profile_id = ?
                """,
                (profile,),
            ).fetchone()
            if row is not None:
                if int(row["dimensions"]) != dimensions:
                    raise BridgeError(
                        "embedding_dimension_mismatch",
                        f"Embedding dimensions changed for profile: {profile}",
                    )
                return str(row["vector_table_name"])

            connection.execute(
                f"""
                CREATE VIRTUAL TABLE IF NOT EXISTS {quoted_vector_table} USING vec0(
                    entry_id TEXT PRIMARY KEY,
                    embedding FLOAT[{dimensions}] distance_metric=cosine,
                    namespace TEXT
                )
                """
            )
            connection.execute(
                f"""
                INSERT INTO {profile_table}(
                    embedding_profile_id, dimensions, vector_table_name
                ) VALUES (?, ?, ?)
                """,
                (profile, dimensions, table_name),
            )
        return table_name

    def _table_for_profile(self, profile: str) -> str:
        profile_table = quote_identifier(self._schema.profile_table)
        with self._connect() as connection:
            row = connection.execute(
                f"""
                SELECT vector_table_name
                FROM {profile_table}
                WHERE embedding_profile_id = ?
                """,
                (profile,),
            ).fetchone()
        if row is None:
            raise BridgeError(
                "dense_profile_missing",
                f"sqlite-vec profile is not indexed: {profile}",
            )
        return str(row["vector_table_name"])


def load_sqlite_vec(connection: sqlite3.Connection) -> None:
    try:
        import sqlite_vec

        connection.enable_load_extension(True)
        try:
            sqlite_vec.load(connection)
        finally:
            connection.enable_load_extension(False)
    except Exception as exc:
        raise BridgeError(
            "sqlite_vec_load_failed",
            "Unable to load sqlite-vec.",
            detail=str(exc),
        ) from exc


def _serialize(vector: np.ndarray) -> bytes:
    return np.asarray(vector, dtype=np.float32).reshape(-1).tobytes()
