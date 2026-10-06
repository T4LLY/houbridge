from __future__ import annotations

from collections import defaultdict
import hashlib
from pathlib import Path
from typing import Protocol, Sequence

import numpy as np

from houbridge.config import HoubridgeConfig, SearchHybridConfig
from houbridge.db.connection import connection_scope
from houbridge.errors import BridgeError
from houbridge.formatting import SearchScoreMetric, format_search_score
from houbridge.paths import WorkspaceSearchPaths
from houbridge.search.dense import DenseIndexSchema, DenseVectorRecord, SQLiteVecIndex
from houbridge.search.embedding import (
    EmbeddingCoordinator,
    EmbeddingItem,
    EmbeddingProvider,
    Model2VecEmbeddingProvider,
    SQLiteEmbeddingCache,
)
from houbridge.search.hybrid import hybrid_rank
from houbridge.search.lexical import LexicalDocument, LexicalIndexSchema, SQLiteFtsIndex
from houbridge.script_search.documents import ScriptDocument, scan_script_documents
from houbridge.script_search.repository import IndexedScript, ScriptIndexRepository


_SCRIPT_NAMESPACE = "workspace-script"
_SCRIPT_LEXICAL_SCHEMA = LexicalIndexSchema(
    entry_table="script_lexical_entries",
    fts_table="script_fts",
)


class DenseScriptIndex(Protocol):
    def upsert(self, profile: str, records: Sequence[DenseVectorRecord]) -> None: ...

    def remove(self, profile: str, entry_ids: Sequence[str]) -> None: ...

    def search_scored(
        self,
        profile: str,
        query_vector: np.ndarray,
        *,
        namespaces: Sequence[str],
        top_k: int,
        entry_ids: Sequence[str] | None = None,
    ) -> list[tuple[str, float]]: ...


class LexicalScriptIndex(Protocol):
    def upsert(self, documents: Sequence[LexicalDocument]) -> None: ...

    def remove(self, entry_ids: Sequence[str]) -> None: ...

    def entry_ids(self, *, namespaces: Sequence[str] | None = None) -> set[str]: ...

    def search(
        self,
        query: str,
        *,
        namespaces: Sequence[str],
        limit: int,
        entry_ids: Sequence[str] | None = None,
    ) -> list[str]: ...


class ScriptSearchService:
    """Reconcile and query one workspace's file-level Python hybrid index."""

    def __init__(
        self,
        *,
        paths: WorkspaceSearchPaths,
        embedding_profile: str,
        enabled: bool,
        hybrid: SearchHybridConfig,
        embeddings: EmbeddingCoordinator | None = None,
        provider: EmbeddingProvider | None = None,
        repository: ScriptIndexRepository | None = None,
        dense_index: DenseScriptIndex | None = None,
        lexical_index: LexicalScriptIndex | None = None,
    ) -> None:
        self.paths = paths
        self.embedding_profile = embedding_profile
        self.enabled = enabled
        self._hybrid = hybrid
        self._embeddings = embeddings
        self._provider = provider
        self._repository = repository
        self._dense_index = dense_index
        self._lexical_index = lexical_index

    @classmethod
    def from_config(
        cls,
        settings: HoubridgeConfig,
        *,
        cwd: Path | None = None,
        provider: EmbeddingProvider | None = None,
    ) -> "ScriptSearchService":
        return cls(
            paths=WorkspaceSearchPaths.for_cwd(cwd),
            embedding_profile=settings.search.embedding.code_profile,
            enabled=settings.local_script_database.enabled,
            hybrid=settings.search.hybrid,
            provider=(provider or Model2VecEmbeddingProvider()),
        )

    def search(
        self,
        query: str,
        *,
        top_k: int = 10,
        include_all: bool = False,
    ) -> dict[str, object]:
        self._require_enabled()
        if not query.strip():
            raise BridgeError("invalid_script_query", "Script search query must not be empty.")
        if top_k < 1 or top_k > 50:
            raise BridgeError("invalid_top_k", "Script search --top-k must be between 1 and 50.")

        current = self._reconcile()
        searchable = (
            current
            if include_all
            else [
                document
                for document in current
                if not document.relative_path.split("/", 1)[0].startswith("_")
            ]
        )
        if not searchable:
            return {"hits": []}

        repository, dense, lexical = self._runtime()
        query_vector = self._encode_query(query)
        current_ids = [document.entry_id for document in searchable]
        scores = hybrid_rank(
            total_count=len(searchable),
            top_k=top_k,
            candidate_min=self._hybrid.candidate_min,
            candidate_multiplier=self._hybrid.candidate_multiplier,
            rrf_k=self._hybrid.rrf_k,
            dense_rank=lambda candidate_limit: [
                entry_id
                for entry_id, _ in dense.search_scored(
                    self.embedding_profile,
                    query_vector,
                    namespaces=[_SCRIPT_NAMESPACE],
                    top_k=candidate_limit,
                    entry_ids=current_ids,
                )
            ],
            lexical_rank=lambda candidate_limit: lexical.search(
                query,
                namespaces=[_SCRIPT_NAMESPACE],
                limit=candidate_limit,
                entry_ids=current_ids,
            ),
        )
        metadata = repository.by_entry_ids(list(scores))
        ordered = sorted(
            (
                (entry_id, score)
                for entry_id, score in scores.items()
                if entry_id in metadata
            ),
            key=lambda item: (-item[1], metadata[item[0]].public_path.casefold()),
        )[:top_k]
        hits: list[dict[str, object]] = []
        for entry_id, raw_score in ordered:
            entry = metadata[entry_id]
            hit: dict[str, object] = {
                "path": entry.public_path,
                "score": format_search_score(
                    raw_score,
                    metric=SearchScoreMetric.RECIPROCAL_RANK_FUSION,
                ),
            }
            if entry.description is not None:
                hit["description"] = entry.description
            hits.append(hit)
        return {"hits": hits}

    def _reconcile(self) -> list[ScriptDocument]:
        repository, dense, lexical = self._runtime()
        documents = scan_script_documents(self.paths.python_directory)
        current_by_path = {document.relative_path: document for document in documents}
        current_ids = {document.entry_id for document in documents}
        existing_by_path = repository.all()
        lexical_ids = lexical.entry_ids(namespaces=[_SCRIPT_NAMESPACE])

        remove_by_profile: dict[str, list[str]] = defaultdict(list)
        remove_metadata: list[str] = []
        changed: list[ScriptDocument] = []
        lexical_changed: list[ScriptDocument] = []

        for relative_path, existing in existing_by_path.items():
            current = current_by_path.get(relative_path)
            current_matches = (
                current is not None
                and existing.content_hash == current.content_hash
                and existing.semantic_hash == current.semantic_hash
                and existing.embedding_profile == self.embedding_profile
            )
            if current_matches:
                continue
            remove_by_profile[existing.embedding_profile].append(existing.entry_id)
            remove_metadata.append(existing.entry_id)

        for relative_path, current in current_by_path.items():
            existing = existing_by_path.get(relative_path)
            if (
                existing is None
                or existing.content_hash != current.content_hash
                or current.entry_id not in lexical_ids
            ):
                lexical_changed.append(current)
            if (
                existing is not None
                and existing.content_hash == current.content_hash
                and existing.semantic_hash == current.semantic_hash
                and existing.embedding_profile == self.embedding_profile
            ):
                continue
            changed.append(current)

        for profile, entry_ids in remove_by_profile.items():
            dense.remove(profile, entry_ids)
        repository.remove(remove_metadata)
        lexical.remove(sorted(lexical_ids - current_ids))

        if lexical_changed:
            lexical.upsert(
                [
                    LexicalDocument(
                        document.entry_id,
                        _SCRIPT_NAMESPACE,
                        document.lexical_text,
                    )
                    for document in lexical_changed
                ]
            )

        if changed:
            vectors = self._encode_documents(changed)
            dense.upsert(
                self.embedding_profile,
                [
                    DenseVectorRecord(
                        entry_id=document.entry_id,
                        namespace=_SCRIPT_NAMESPACE,
                        vector=vectors[document.semantic_hash],
                    )
                    for document in changed
                ],
            )
            repository.replace(
                [
                    IndexedScript(
                        entry_id=document.entry_id,
                        relative_path=document.relative_path,
                        public_path=document.public_path,
                        content_hash=document.content_hash,
                        semantic_hash=document.semantic_hash,
                        description=document.description,
                        embedding_profile=self.embedding_profile,
                    )
                    for document in changed
                ]
            )
        return documents

    def _runtime(
        self,
    ) -> tuple[ScriptIndexRepository, DenseScriptIndex, LexicalScriptIndex]:
        if (
            self._repository is not None
            and self._dense_index is not None
            and self._lexical_index is not None
        ):
            return self._repository, self._dense_index, self._lexical_index

        self.paths.workspace_directory.mkdir(parents=True, exist_ok=True)
        def factory():
            return connection_scope(self.paths.search_database)
        repository = self._repository or ScriptIndexRepository(factory)
        dense = self._dense_index or SQLiteVecIndex(
            factory,
            schema=DenseIndexSchema(
                profile_table="script_vector_profiles",
                vector_table_prefix="script_vec",
            ),
        )
        lexical = self._lexical_index or SQLiteFtsIndex(
            factory,
            schema=_SCRIPT_LEXICAL_SCHEMA,
        )
        if self._embeddings is None:
            self._embeddings = EmbeddingCoordinator(
                self._provider or Model2VecEmbeddingProvider(),
                SQLiteEmbeddingCache(factory, table_name="script_embedding_cache"),
            )
        self._repository = repository
        self._dense_index = dense
        self._lexical_index = lexical
        return repository, dense, lexical

    def _encode_documents(self, documents: Sequence[ScriptDocument]) -> dict[str, np.ndarray]:
        embeddings = self._embedding_coordinator()
        return embeddings.encode(
            [
                EmbeddingItem(
                    content_hash=document.semantic_hash,
                    text=document.semantic_text,
                )
                for document in documents
            ],
            profile=self.embedding_profile,
        )

    def _encode_query(self, query: str) -> np.ndarray:
        embeddings = self._embedding_coordinator()
        query_hash = _sha256_text(query)
        vectors = embeddings.encode(
            [EmbeddingItem(content_hash=query_hash, text=query)],
            profile=self.embedding_profile,
        )
        return vectors[query_hash]

    def _embedding_coordinator(self) -> EmbeddingCoordinator:
        if self._embeddings is None:
            raise RuntimeError("Script Search embedding runtime is not initialized")
        return self._embeddings

    def _require_enabled(self) -> None:
        if not self.enabled:
            raise BridgeError(
                "local_script_database_disabled",
                "Local script database features are disabled by configuration.",
            )


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
