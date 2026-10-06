from __future__ import annotations

import os
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Protocol

import numpy as np

from houbridge.errors import BridgeError
from houbridge.search.sqlite_filter import quote_identifier


class EmbeddingProvider(Protocol):
    def encode(self, texts: Sequence[str], profile: str) -> np.ndarray: ...


class EmbeddingCache(Protocol):
    def get(self, profile: str, content_hash: str) -> np.ndarray | None: ...

    def put(self, profile: str, content_hash: str, vector: np.ndarray) -> None: ...


class Model2VecEmbeddingProvider:
    """Lazy Model2Vec provider with one in-process model per explicit profile."""

    def __init__(self) -> None:
        self._models: dict[str, object] = {}

    def encode(self, texts: Sequence[str], profile: str) -> np.ndarray:
        if not profile.strip():
            raise ValueError("embedding profile must not be empty")
        if not texts:
            return np.empty((0, 0), dtype=np.float32)

        model = self._models.get(profile)
        if model is None:
            try:
                os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
                from huggingface_hub.utils import disable_progress_bars
                from model2vec import StaticModel

                with disable_progress_bars():
                    model = StaticModel.from_pretrained(profile)
            except Exception as exc:
                raise BridgeError(
                    "embedding_model_load_failed",
                    f"Unable to load embedding profile: {profile}",
                    detail=str(exc),
                ) from exc
            self._models[profile] = model

        try:
            vectors = model.encode(list(texts))  # type: ignore[attr-defined]
        except Exception as exc:
            raise BridgeError(
                "embedding_failed",
                f"Embedding failed for profile: {profile}",
                detail=str(exc),
            ) from exc

        array = np.asarray(vectors, dtype=np.float32)
        if array.ndim == 1:
            array = array[None, :]
        if array.ndim != 2 or array.shape[0] != len(texts):
            raise BridgeError(
                "embedding_failed",
                f"Embedding provider returned an invalid shape for profile: {profile}",
            )
        return array


ConnectionFactory = Callable[[], AbstractContextManager[object]]


class SQLiteEmbeddingCache:
    """Profile-aware embedding cache inside a caller-owned SQLite database."""

    def __init__(self, connection_factory: ConnectionFactory, *, table_name: str) -> None:
        self._connection_factory = connection_factory
        self._table = quote_identifier(table_name)
        self._initialize()

    def _initialize(self) -> None:
        with self._connection_factory() as connection:
            connection.execute(  # type: ignore[attr-defined]
                f"""
                CREATE TABLE IF NOT EXISTS {self._table}(
                    embedding_profile_id TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    dimensions INTEGER NOT NULL,
                    embedding BLOB NOT NULL,
                    PRIMARY KEY(embedding_profile_id, content_hash)
                ) WITHOUT ROWID
                """
            )

    def get(self, profile: str, content_hash: str) -> np.ndarray | None:
        with self._connection_factory() as connection:
            row = connection.execute(  # type: ignore[attr-defined]
                f"""
                SELECT dimensions, embedding
                FROM {self._table}
                WHERE embedding_profile_id = ? AND content_hash = ?
                """,
                (profile, content_hash),
            ).fetchone()
        if row is None:
            return None
        dimensions = int(row["dimensions"])
        vector = np.frombuffer(bytes(row["embedding"]), dtype=np.float32)
        if vector.size != dimensions:
            raise BridgeError(
                "embedding_cache_corrupt",
                "Cached embedding dimensions do not match the stored payload.",
            )
        return vector.copy()

    def put(self, profile: str, content_hash: str, vector: np.ndarray) -> None:
        normalized = _vector(vector)
        with self._connection_factory() as connection:
            connection.execute(  # type: ignore[attr-defined]
                f"""
                INSERT INTO {self._table}(
                    embedding_profile_id, content_hash, dimensions, embedding
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT(embedding_profile_id, content_hash) DO UPDATE SET
                    dimensions = excluded.dimensions,
                    embedding = excluded.embedding
                """,
                (profile, content_hash, normalized.size, normalized.tobytes()),
            )


@dataclass(frozen=True)
class EmbeddingItem:
    content_hash: str
    text: str


class EmbeddingCoordinator:
    """Resolve content/profile vectors through a cache without owning storage."""

    def __init__(self, provider: EmbeddingProvider, cache: EmbeddingCache | None = None) -> None:
        self._provider = provider
        self._cache = cache

    def encode(
        self,
        items: Sequence[EmbeddingItem],
        *,
        profile: str,
    ) -> dict[str, np.ndarray]:
        if not profile.strip():
            raise ValueError("embedding profile must not be empty")
        if not items:
            return {}

        texts_by_hash: dict[str, str] = {}
        for item in items:
            existing = texts_by_hash.get(item.content_hash)
            if existing is not None and existing != item.text:
                raise ValueError("one content hash cannot refer to multiple texts")
            texts_by_hash[item.content_hash] = item.text

        resolved: dict[str, np.ndarray] = {}
        missing_hashes: list[str] = []
        missing_texts: list[str] = []
        for content_hash, text in texts_by_hash.items():
            cached = self._cache.get(profile, content_hash) if self._cache else None
            if cached is None:
                missing_hashes.append(content_hash)
                missing_texts.append(text)
            else:
                resolved[content_hash] = _vector(cached)

        if missing_texts:
            encoded = np.asarray(
                self._provider.encode(missing_texts, profile),
                dtype=np.float32,
            )
            if encoded.ndim != 2 or encoded.shape[0] != len(missing_texts):
                raise BridgeError(
                    "embedding_failed",
                    f"Embedding provider returned an invalid shape for profile: {profile}",
                )
            for content_hash, row in zip(missing_hashes, encoded, strict=True):
                vector = _vector(row)
                resolved[content_hash] = vector
                if self._cache:
                    self._cache.put(profile, content_hash, vector)

        return resolved


def _vector(value: np.ndarray) -> np.ndarray:
    normalized = np.asarray(value, dtype=np.float32).reshape(-1)
    if normalized.size == 0:
        raise ValueError("embedding vector must not be empty")
    return normalized
