from __future__ import annotations

import hashlib
from collections.abc import Sequence
from pathlib import Path

from houbridge.config import SearchHybridConfig
from houbridge.db.connection import connection_scope
from houbridge.search.dense import DenseIndexSchema, DenseVectorRecord, SQLiteVecIndex
from houbridge.search.embedding import EmbeddingCoordinator, EmbeddingItem, EmbeddingProvider
from houbridge.search.lexical import LexicalDocument, LexicalIndexSchema, SQLiteFtsIndex
from houbridge.search.rrf import reciprocal_rank_fusion
from houbridge.temporary_workspace import TemporaryWorkspaceService

from .models import LiveCodeEntry, RankedLiveCode


_LIVE_NAMESPACE = "live-code"


class TransientLiveCodeRanker:
    """Build one invocation-local index and discard it after ranking."""

    def __init__(
        self,
        *,
        embedding_profile: str,
        provider: EmbeddingProvider,
        hybrid: SearchHybridConfig,
        workspaces: TemporaryWorkspaceService | None = None,
    ) -> None:
        self._embedding_profile = embedding_profile
        self._provider = provider
        self._hybrid = hybrid
        self._workspaces = workspaces or TemporaryWorkspaceService()

    def hybrid(
        self,
        entries: Sequence[LiveCodeEntry],
        query: str,
        *,
        top_k: int,
    ) -> list[RankedLiveCode]:
        if not entries:
            return []
        workspace = self._workspaces.allocate(prefix="live-code-index")
        try:
            factory = lambda: connection_scope(workspace.path_for("index.db"))
            dense = self._dense_index(factory)
            lexical = SQLiteFtsIndex(
                factory,
                schema=LexicalIndexSchema(
                    entry_table="live_lexical_entries",
                    fts_table="live_fts",
                ),
            )
            vectors, query_vector = self._vectors(entries, query)
            dense.upsert(
                self._embedding_profile,
                [
                    DenseVectorRecord(entry.entry_id, _LIVE_NAMESPACE, vectors[entry.entry_id])
                    for entry in entries
                ],
            )
            lexical.upsert(
                [
                    LexicalDocument(entry.entry_id, _LIVE_NAMESPACE, entry.source)
                    for entry in entries
                ]
            )
            candidate_limit = min(
                len(entries),
                max(
                    self._hybrid.candidate_min,
                    top_k * self._hybrid.candidate_multiplier,
                ),
            )
            dense_ids = [
                entry_id
                for entry_id, _ in dense.search_scored(
                    self._embedding_profile,
                    query_vector,
                    namespaces=[_LIVE_NAMESPACE],
                    top_k=candidate_limit,
                )
            ]
            lexical_ids = lexical.search(
                query,
                namespaces=[_LIVE_NAMESPACE],
                limit=candidate_limit,
            )
            scores = reciprocal_rank_fusion(
                [dense_ids, lexical_ids],
                k=self._hybrid.rrf_k,
            )
            by_id = {entry.entry_id: entry for entry in entries}
            ordered = sorted(
                scores.items(),
                key=lambda item: (
                    -item[1],
                    by_id[item[0]].path.casefold(),
                    by_id[item[0]].slot_id.casefold(),
                ),
            )
            return [
                RankedLiveCode(by_id[entry_id], score)
                for entry_id, score in ordered[:top_k]
            ]
        finally:
            workspace.remove()

    def dense(
        self,
        entries: Sequence[LiveCodeEntry],
        query_source: str,
        *,
        top_k: int,
    ) -> list[RankedLiveCode]:
        if not entries:
            return []
        workspace = self._workspaces.allocate(prefix="live-code-index")
        try:
            factory = lambda: connection_scope(workspace.path_for("index.db"))
            dense = self._dense_index(factory)
            vectors, query_vector = self._vectors(entries, query_source)
            dense.upsert(
                self._embedding_profile,
                [
                    DenseVectorRecord(entry.entry_id, _LIVE_NAMESPACE, vectors[entry.entry_id])
                    for entry in entries
                ],
            )
            by_id = {entry.entry_id: entry for entry in entries}
            ranked = dense.search_scored(
                self._embedding_profile,
                query_vector,
                namespaces=[_LIVE_NAMESPACE],
                top_k=min(top_k, len(entries)),
            )
            return [
                RankedLiveCode(by_id[entry_id], score)
                for entry_id, score in ranked
                if entry_id in by_id
            ]
        finally:
            workspace.remove()

    def _dense_index(self, factory):
        return SQLiteVecIndex(
            factory,
            schema=DenseIndexSchema(
                profile_table="live_vector_profiles",
                vector_table_prefix="live_vec",
            ),
        )

    def _vectors(
        self,
        entries: Sequence[LiveCodeEntry],
        query: str,
    ):
        coordinator = EmbeddingCoordinator(self._provider)
        items = [
            EmbeddingItem(content_hash=_entry_hash(entry), text=entry.source)
            for entry in entries
        ]
        query_hash = _sha256_text(query)
        items.append(EmbeddingItem(content_hash=query_hash, text=query))
        resolved = coordinator.encode(items, profile=self._embedding_profile)
        vectors = {entry.entry_id: resolved[_entry_hash(entry)] for entry in entries}
        return vectors, resolved[query_hash]


def _entry_hash(entry: LiveCodeEntry) -> str:
    return _sha256_text(entry.source)


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
