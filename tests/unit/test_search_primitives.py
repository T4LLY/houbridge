from __future__ import annotations

import os
import sqlite3
import sys
import types
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path

import numpy as np
import pytest

from houbridge.db.connection import connection_scope
from houbridge.formatting import SearchScoreMetric, format_search_score
from houbridge.search.dense import DenseIndexSchema, SQLiteVecIndex
from houbridge.search.embedding import (
    EmbeddingCoordinator,
    EmbeddingItem,
    Model2VecEmbeddingProvider,
    SQLiteEmbeddingCache,
)
from houbridge.search.lexical import LexicalDocument, LexicalIndexSchema, SQLiteFtsIndex
from houbridge.search.rrf import reciprocal_rank_fusion


def _factory(path: Path):
    return lambda: connection_scope(path)


class _Provider:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[str, ...]]] = []

    def encode(self, texts, profile: str) -> np.ndarray:
        self.calls.append((profile, tuple(texts)))
        base = 1.0 if profile == "profile-a" else 10.0
        return np.asarray(
            [[base + index, base + index + 0.5] for index, _ in enumerate(texts)],
            dtype=np.float32,
        )



def test_model2vec_provider_loads_each_profile_once_without_progress_noise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[object] = []
    monkeypatch.delenv("HF_HUB_DISABLE_SYMLINKS_WARNING", raising=False)

    class _ProgressContext:
        def __enter__(self):
            events.append("progress-disabled")
            return self

        def __exit__(self, exc_type, exc, tb):
            events.append("progress-restored")
            return False

    def disable_progress_bars():
        return _ProgressContext()

    class _Model:
        def encode(self, texts):
            return np.ones((len(texts), 2), dtype=np.float32)

    class _StaticModel:
        @classmethod
        def from_pretrained(cls, profile: str):
            events.append(("load", profile))
            return _Model()

    hub_module = types.ModuleType("huggingface_hub")
    hub_utils_module = types.ModuleType("huggingface_hub.utils")
    hub_utils_module.disable_progress_bars = disable_progress_bars
    hub_module.utils = hub_utils_module
    model2vec_module = types.ModuleType("model2vec")
    model2vec_module.StaticModel = _StaticModel
    monkeypatch.setitem(sys.modules, "huggingface_hub", hub_module)
    monkeypatch.setitem(sys.modules, "huggingface_hub.utils", hub_utils_module)
    monkeypatch.setitem(sys.modules, "model2vec", model2vec_module)

    provider = Model2VecEmbeddingProvider()
    provider.encode(["one"], "profile-a")
    provider.encode(["two"], "profile-a")
    provider.encode(["three"], "profile-b")

    assert os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] == "1"
    assert events == [
        "progress-disabled",
        ("load", "profile-a"),
        "progress-restored",
        "progress-disabled",
        ("load", "profile-b"),
        "progress-restored",
    ]

def test_embedding_cache_is_keyed_by_content_and_profile(tmp_path: Path) -> None:
    database = tmp_path / "search.db"
    cache = SQLiteEmbeddingCache(_factory(database), table_name="script_embedding_cache")
    provider = _Provider()
    coordinator = EmbeddingCoordinator(provider, cache)
    item = EmbeddingItem(content_hash="same-content", text="print('same')")

    first = coordinator.encode([item], profile="profile-a")
    again = coordinator.encode([item], profile="profile-a")
    other_profile = coordinator.encode([item], profile="profile-b")

    np.testing.assert_array_equal(first["same-content"], again["same-content"])
    assert provider.calls == [
        ("profile-a", ("print('same')",)),
        ("profile-b", ("print('same')",)),
    ]
    assert not np.array_equal(first["same-content"], other_profile["same-content"])

    with sqlite3.connect(database) as connection:
        rows = connection.execute(
            """
            SELECT embedding_profile_id, content_hash
            FROM script_embedding_cache
            ORDER BY embedding_profile_id
            """
        ).fetchall()
    assert rows == [
        ("profile-a", "same-content"),
        ("profile-b", "same-content"),
    ]


def test_embedding_coordinator_batches_only_cache_misses(tmp_path: Path) -> None:
    cache = SQLiteEmbeddingCache(_factory(tmp_path / "search.db"), table_name="embedding_cache")
    provider = _Provider()
    coordinator = EmbeddingCoordinator(provider, cache)

    coordinator.encode(
        [
            EmbeddingItem(content_hash="a", text="alpha"),
            EmbeddingItem(content_hash="b", text="beta"),
        ],
        profile="profile-a",
    )
    coordinator.encode(
        [
            EmbeddingItem(content_hash="a", text="alpha"),
            EmbeddingItem(content_hash="c", text="gamma"),
        ],
        profile="profile-a",
    )

    assert provider.calls == [
        ("profile-a", ("alpha", "beta")),
        ("profile-a", ("gamma",)),
    ]


def test_dense_schema_keeps_profiles_in_distinct_vector_tables() -> None:
    schema = DenseIndexSchema(
        profile_table="script_vector_profiles",
        vector_table_prefix="script_vec",
    )

    assert schema.vector_table_name("profile-a") != schema.vector_table_name("profile-b")
    assert schema.vector_table_name("profile-a").startswith("script_vec_")


def test_dense_search_uses_sqlite_vec_cosine_distance_without_public_scaling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queries: list[tuple[str, tuple[object, ...] | None]] = []

    class _Rows:
        def __init__(self, rows):
            self._rows = rows

        def fetchone(self):
            return self._rows[0] if self._rows else None

        def fetchall(self):
            return self._rows

    class _Connection:
        def execute(self, sql, params=None):
            normalized = " ".join(sql.split())
            queries.append((normalized, tuple(params) if params is not None else None))
            if "SELECT vector_table_name" in normalized:
                return _Rows([{"vector_table_name": "script_vec_profile"}])
            if "SELECT entry_id, distance" in normalized:
                return _Rows(
                    [
                        {"entry_id": "a", "distance": 0.1},
                        {"entry_id": "b", "distance": 0.25},
                    ]
                )
            return _Rows([])

    @contextmanager
    def connection_factory():
        yield _Connection()

    monkeypatch.setattr("houbridge.search.dense.load_sqlite_vec", lambda _connection: None)
    index = SQLiteVecIndex(
        connection_factory,
        schema=DenseIndexSchema(
            profile_table="script_vector_profiles",
            vector_table_prefix="script_vec",
        ),
    )
    queries.clear()

    results = index.search_scored(
        "profile-a",
        np.asarray([1.0, 0.0], dtype=np.float32),
        namespaces=["python"],
        entry_ids=["a", "b"],
        top_k=2,
    )

    assert results == [("a", 0.9), ("b", 0.75)]
    knn_sql, knn_params = next(
        (sql, params) for sql, params in queries if "SELECT entry_id, distance" in sql
    )
    assert "embedding MATCH ?" in knn_sql
    assert "k = ?" in knn_sql
    assert "ORDER BY distance" in knn_sql
    assert knn_params is not None and knn_params[1] == 2


def test_fts5_bm25_search_supports_namespace_and_membership_filters(tmp_path: Path) -> None:
    database = tmp_path / "search.db"
    index = SQLiteFtsIndex(
        _factory(database),
        schema=LexicalIndexSchema(entry_table="script_lexical_entries", fts_table="script_fts"),
    )
    index.upsert(
        [
            LexicalDocument("a", "python", "node geometry transform"),
            LexicalDocument("b", "python", "node material shader"),
            LexicalDocument("c", "vex", "node geometry vex"),
        ]
    )

    assert index.search("geometry", namespaces=["python"], limit=10) == ["a"]
    assert index.search(
        "node",
        namespaces=["python"],
        entry_ids=["b"],
        limit=10,
    ) == ["b"]

    with sqlite3.connect(database) as connection:
        stored = connection.execute(
            "SELECT content FROM script_fts WHERE rowid = (SELECT fts_id FROM script_lexical_entries WHERE entry_id = 'a')"
        ).fetchone()[0]
    assert stored is None


def test_rrf_fuses_rank_positions_without_combining_raw_metric_scores() -> None:
    scores = reciprocal_rank_fusion(
        [["a", "b"], ["b", "c"]],
        k=60,
    )

    assert scores["b"] > scores["a"]
    assert scores["b"] > scores["c"]
    assert scores["a"] == pytest.approx(1 / 61)
    assert scores["c"] == pytest.approx(1 / 62)


def test_public_dense_and_rrf_scores_use_the_shared_phase1_formatter() -> None:
    dense = format_search_score(
        Decimal("0.30127891"),
        metric=SearchScoreMetric.DENSE_COSINE,
    )
    rrf = format_search_score(
        Decimal("0.0317540323"),
        metric=SearchScoreMetric.RECIPROCAL_RANK_FUSION,
    )

    assert dense.token == "301.278910"
    assert rrf.token == "317.540323"
