from __future__ import annotations

from pathlib import Path

import numpy as np

from houbridge.config import SearchHybridConfig
from houbridge.live_code_search.models import LiveCodeEntry
from houbridge.live_code_search import ranking
from houbridge.live_code_search.ranking import TransientLiveCodeRanker
from houbridge.temporary_workspace import TemporaryWorkspaceService


class _Provider:
    def encode(self, texts, profile: str):
        del profile
        return np.asarray(
            [[float(index + 1), 1.0] for index, _text in enumerate(texts)],
            dtype=np.float32,
        )


class _Dense:
    def __init__(self, _factory, *, schema) -> None:
        del schema
        self.ids = []

    def upsert(self, profile, records) -> None:
        del profile
        self.ids = [record.entry_id for record in records]

    def search_scored(self, profile, query_vector, *, namespaces, top_k, entry_ids=None):
        del profile, query_vector, namespaces, entry_ids
        return [(entry_id, 0.9 - index * 0.1) for index, entry_id in enumerate(self.ids[:top_k])]


class _Lexical:
    def __init__(self, _factory, *, schema) -> None:
        del schema
        self.ids = []

    def upsert(self, documents) -> None:
        self.ids = [document.entry_id for document in documents]

    def search(self, query, *, namespaces, limit, entry_ids=None):
        del query, namespaces, entry_ids
        return list(reversed(self.ids))[:limit]


def _entry(session_id: int, path: str, source: str) -> LiveCodeEntry:
    return LiveCodeEntry(
        session_id=session_id,
        path=path,
        node_type="python",
        slot_id="python-node:python",
        parameter_name="python",
        language="python",
        source=source,
    )


def test_live_hybrid_index_is_invocation_local_and_removed_after_search(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(ranking, "SQLiteVecIndex", _Dense)
    monkeypatch.setattr(ranking, "SQLiteFtsIndex", _Lexical)
    temp_root = tmp_path / "temp"
    ranker = TransientLiveCodeRanker(
        embedding_profile="code-profile",
        provider=_Provider(),
        hybrid=SearchHybridConfig(rrf_k=60, candidate_multiplier=8, candidate_min=32),
        workspaces=TemporaryWorkspaceService(temp_root=temp_root),
    )

    result = ranker.hybrid(
        [
            _entry(1, "/obj/python1", "build geometry"),
            _entry(2, "/obj/python2", "render preview"),
        ],
        "geometry",
        top_k=2,
    )

    assert len(result) == 2
    assert list((temp_root / "houbridge" / "workspaces").glob("live-code-index-*")) == []
    assert not (tmp_path / ".houbridge" / "search.db").exists()
