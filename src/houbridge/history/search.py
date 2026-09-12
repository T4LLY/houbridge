from __future__ import annotations

import sqlite3
from collections import defaultdict

import numpy as np

from houbridge.config import SearchHybridConfig
from houbridge.history.locking import (
    HistoryDatabaseMissingError,
    history_connection_scope,
)
from houbridge.errors import BridgeError
from houbridge.formatting import SearchScoreMetric, format_search_score
from houbridge.search.dense import DenseVectorRecord, SQLiteVecIndex
from houbridge.search.embedding import EmbeddingProvider, Model2VecEmbeddingProvider, SQLiteEmbeddingCache
from houbridge.search.lexical import LexicalDocument, SQLiteFtsIndex
from houbridge.search.rrf import reciprocal_rank_fusion

from .reader import HistoryEntryRecord, HistoryReader
from .search_schema import (
    DENSE_NAMESPACE,
    DENSE_SCHEMA,
    LEXICAL_NAMESPACE,
    LEXICAL_SCHEMA,
    SOURCE_EMBEDDING_TABLE,
)
from .store import HistoryStore


class HistorySearchService:
    """Hybrid recall over one exact process-incarnation Action History."""

    def __init__(
        self,
        store: HistoryStore | None,
        *,
        provider: EmbeddingProvider | None = None,
        hybrid: SearchHybridConfig,
    ) -> None:
        self._store = store
        self._provider = provider or Model2VecEmbeddingProvider()
        self._hybrid = hybrid

    def search(self, query: str, *, top_k: int = 10) -> dict[str, object]:
        normalized_query = query.strip()
        if not normalized_query:
            raise BridgeError("invalid_history_query", "History search QUERY must not be empty.")
        if top_k < 1 or top_k > 50:
            raise BridgeError(
                "invalid_history_top_k",
                "--top-k must be an integer from 1 through 50.",
            )
        if self._store is None:
            return {"hits": []}

        profile = self._store.code_profile()
        if profile is None or not profile.strip():
            raise BridgeError(
                "history_store_invalid",
                "History database is missing its code embedding profile.",
            )
        reader = HistoryReader(
            self._store.database,
            lock_timeout_seconds=self._store.lock_timeout_seconds,
        )
        entries = reader.all_for_search()
        if not entries:
            return {"hits": []}

        try:
            dense, lexical = self._synchronize_indexes(entries, profile)
            query_vector = self._query_vector(normalized_query, profile)
            candidate_limit = min(
                len(entries),
                max(
                    self._hybrid.candidate_min,
                    top_k * self._hybrid.candidate_multiplier,
                ),
            )

            source_groups: dict[str, list[HistoryEntryRecord]] = defaultdict(list)
            for entry in entries:
                source_groups[entry.source_hash].append(entry)
            dense_source_ids = dense.search(
                profile,
                query_vector,
                namespaces=[DENSE_NAMESPACE],
                top_k=min(candidate_limit, len(source_groups)),
            )
            dense_entry_ids: list[str] = []
            for source_hash in dense_source_ids:
                dense_entry_ids.extend(
                    str(entry.id)
                    for entry in sorted(
                        source_groups.get(source_hash, ()),
                        key=lambda item: -item.id,
                    )
                )

            lexical_entry_ids = lexical.search(
                normalized_query,
                namespaces=[LEXICAL_NAMESPACE],
                limit=candidate_limit,
            )
        except HistoryDatabaseMissingError:
            return {"hits": []}
        except BridgeError:
            raise
        except sqlite3.Error as exc:
            raise BridgeError(
                "history_store_failed",
                "History database operation failed.",
                str(exc),
            ) from exc

        scores = reciprocal_rank_fusion(
            [dense_entry_ids, lexical_entry_ids],
            k=self._hybrid.rrf_k,
        )
        by_id = {str(entry.id): entry for entry in entries}
        ordered = sorted(
            (
                (entry_id, score)
                for entry_id, score in scores.items()
                if entry_id in by_id
            ),
            key=lambda item: (-item[1], -by_id[item[0]].id),
        )[:top_k]

        hits: list[dict[str, object]] = []
        for entry_id, score in ordered:
            entry = by_id[entry_id]
            item: dict[str, object] = {
                "id": entry.id,
                "score": format_search_score(
                    score,
                    metric=SearchScoreMetric.RECIPROCAL_RANK_FUSION,
                ),
                "time": entry.public_list_item()["time"],
            }
            if entry.purpose:
                item["purpose"] = entry.purpose
            hits.append(item)
        return {"hits": hits}

    def _synchronize_indexes(
        self,
        entries: list[HistoryEntryRecord],
        profile: str,
    ) -> tuple[SQLiteVecIndex, SQLiteFtsIndex]:
        assert self._store is not None
        factory = lambda: history_connection_scope(
            self._store.database,
            require_existing=True,
            lock_timeout_seconds=self._store.lock_timeout_seconds,
        )
        cache = SQLiteEmbeddingCache(factory, table_name=SOURCE_EMBEDDING_TABLE)
        dense = SQLiteVecIndex(factory, schema=DENSE_SCHEMA)
        lexical = SQLiteFtsIndex(factory, schema=LEXICAL_SCHEMA)

        vectors: list[DenseVectorRecord] = []
        for source_hash in sorted({entry.source_hash for entry in entries}):
            vector = cache.get(profile, source_hash)
            if vector is None:
                raise BridgeError(
                    "history_store_invalid",
                    "History source embedding is missing for a recorded action.",
                    source_hash,
                )
            vectors.append(DenseVectorRecord(source_hash, DENSE_NAMESPACE, vector))
        dense.upsert(profile, vectors)
        lexical.upsert(
            [
                LexicalDocument(
                    str(entry.id),
                    LEXICAL_NAMESPACE,
                    _lexical_projection(entry),
                )
                for entry in entries
            ]
        )
        return dense, lexical

    def _query_vector(self, query: str, profile: str) -> np.ndarray:
        try:
            encoded = np.asarray(self._provider.encode([query], profile), dtype=np.float32)
        except BridgeError:
            raise
        except Exception as exc:
            raise BridgeError(
                "embedding_failed",
                f"Embedding failed for profile: {profile}",
                f"{type(exc).__name__}: {exc}",
            ) from exc
        if encoded.ndim == 1:
            encoded = encoded[None, :]
        if encoded.ndim != 2 or encoded.shape[0] != 1 or encoded.shape[1] <= 0:
            raise BridgeError(
                "embedding_failed",
                f"Embedding provider returned an invalid shape for profile: {profile}",
            )
        return encoded[0].copy()


def _lexical_projection(entry: HistoryEntryRecord) -> str:
    parts = [entry.cwd, entry.file, *entry.args]
    if entry.purpose:
        parts.append(entry.purpose)
    for change in entry.changes:
        _append_scalars(parts, change)
    return "\n".join(part for part in parts if part)


def _append_scalars(parts: list[str], value: object) -> None:
    if value is None:
        return
    if isinstance(value, bool):
        parts.append("true" if value else "false")
        return
    if isinstance(value, (str, int, float)):
        parts.append(str(value))
        return
    if isinstance(value, dict):
        for key in sorted(value):
            parts.append(str(key))
            _append_scalars(parts, value[key])
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            _append_scalars(parts, item)
