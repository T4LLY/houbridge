from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from typer.testing import CliRunner

from houbridge.cli import history_cmd
from houbridge.cli.main import app
from houbridge.config import SearchHybridConfig
from houbridge.errors import BridgeError
from houbridge.history.changes import ParmChangedChange
from houbridge.history.reader import HistoryEntryRecord, HistoryReadService, HistoryReader
from houbridge.history.search import HistorySearchService
from houbridge.history.store import HistoryStore
from houbridge.output.policy import OutputPolicy
from houbridge.process_coordination import ProcessIdentity
from houbridge.session.resolver import ResolvedSession


class FakeEmbeddingProvider:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[str, ...]]] = []

    def encode(self, texts, profile: str) -> np.ndarray:
        values = tuple(texts)
        self.calls.append((profile, values))
        return np.asarray(
            [[float(index + 1), 1.0, 0.5] for index, _ in enumerate(values)],
            dtype=np.float32,
        )


class FakeDenseIndex:
    records = []
    upsert_calls = []

    def __init__(self, _factory, *, schema) -> None:
        self.schema = schema

    def upsert(self, _profile: str, records) -> None:
        type(self).records = list(records)
        type(self).upsert_calls.append([record.entry_id for record in records])

    def search(self, _profile: str, _query_vector, *, namespaces, top_k: int):
        assert namespaces == ["history-source"]
        return [record.entry_id for record in type(self).records[:top_k]]


def _store_with_two_entries(tmp_path: Path) -> tuple[HistoryStore, str]:
    provider = FakeEmbeddingProvider()
    store = HistoryStore(tmp_path / "history.db", embedding_provider=provider)
    source = "hou.node('/obj').createNode('box')\n"
    embedded = store.embed_source(source, requested_code_profile="profile-a")
    store.commit_entry(
        expected_code_profile="profile-a",
        time="2026-09-09T13:20:00",
        cwd=str(tmp_path.resolve()),
        status="completed",
        file=str((tmp_path / "first.py").resolve()),
        args=("--quality", "low"),
        purpose="first pass",
        source_hash=embedded.source_hash,
        changes=(),
    )
    store.commit_entry(
        expected_code_profile="profile-a",
        time="2026-09-09T13:24:10.123456",
        cwd=str(tmp_path.resolve()),
        status="failed",
        file=str((tmp_path / "second.py").resolve()),
        args=("--quality", "high"),
        purpose="build preview geometry",
        source_hash=embedded.source_hash,
        changes=(
            ParmChangedChange(
                node=417,
                path="/obj/geo1/box1",
                parm="sizex",
                before="1",
                after="2",
            ),
        ),
    )
    return store, embedded.source_hash


def test_history_search_fuses_source_semantics_and_lexical_action_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, source_hash = _store_with_two_entries(tmp_path)
    FakeDenseIndex.records = []
    monkeypatch.setattr("houbridge.history.search.SQLiteVecIndex", FakeDenseIndex)
    provider = FakeEmbeddingProvider()
    service = HistorySearchService(
        store,
        provider=provider,
        hybrid=SearchHybridConfig(rrf_k=60, candidate_multiplier=4, candidate_min=20),
    )

    payload = service.search("sizex", top_k=10)

    assert [hit["id"] for hit in payload["hits"]] == [2, 1]
    assert payload["hits"][0]["time"] == "2026-09-09T13:24:10"
    assert payload["hits"][0]["purpose"] == "build preview geometry"
    assert "purpose" in payload["hits"][1]
    assert len(FakeDenseIndex.records) == 1
    assert FakeDenseIndex.records[0].entry_id == source_hash
    assert provider.calls == [("profile-a", ("sizex",))]
    score = payload["hits"][0]["score"]
    assert getattr(score, "token") == "327.868852"


def test_history_search_does_not_reindex_unchanged_entries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, source_hash = _store_with_two_entries(tmp_path)
    FakeDenseIndex.records = []
    FakeDenseIndex.upsert_calls = []
    monkeypatch.setattr("houbridge.history.search.SQLiteVecIndex", FakeDenseIndex)

    from houbridge.search.lexical import SQLiteFtsIndex

    lexical_upserts: list[list[str]] = []
    original_upsert = SQLiteFtsIndex.upsert

    def tracking_upsert(self, documents) -> None:
        batch = list(documents)
        lexical_upserts.append([document.entry_id for document in batch])
        original_upsert(self, batch)

    monkeypatch.setattr(SQLiteFtsIndex, "upsert", tracking_upsert)
    service = HistorySearchService(
        store,
        provider=FakeEmbeddingProvider(),
        hybrid=SearchHybridConfig(rrf_k=60, candidate_multiplier=4, candidate_min=20),
    )

    first = service.search("sizex", top_k=10)
    second = service.search("sizex", top_k=10)

    assert first == second
    assert FakeDenseIndex.upsert_calls == [[source_hash]]
    assert lexical_upserts == [["1", "2"]]


def test_history_get_and_list_use_public_shapes_and_newest_first(tmp_path: Path) -> None:
    store, _ = _store_with_two_entries(tmp_path)
    service = HistoryReadService(HistoryReader(store.database))

    full = service.get(2)
    listed = service.list(20)

    assert full == {
        "id": 2,
        "time": "2026-09-09T13:24:10",
        "status": "failed",
        "cwd": str(tmp_path.resolve()),
        "file": str((tmp_path / "second.py").resolve()),
        "args": ["--quality", "high"],
        "purpose": "build preview geometry",
        "changes": [
            {
                "type": "parm_changed",
                "node": 417,
                "path": "/obj/geo1/box1",
                "parm": "sizex",
                "before": "1",
                "after": "2",
            }
        ],
    }
    assert [entry["id"] for entry in listed["entries"]] == [2, 1]
    assert set(listed["entries"][0]) == {"id", "time", "status", "file", "purpose"}


def test_missing_current_history_is_empty_for_search_and_list_and_get_is_not_found() -> None:
    hybrid = SearchHybridConfig(rrf_k=60, candidate_multiplier=4, candidate_min=20)
    assert HistorySearchService(None, provider=FakeEmbeddingProvider(), hybrid=hybrid).search("x") == {
        "hits": []
    }
    service = HistoryReadService(None)
    assert service.list(20) == {"entries": []}
    with pytest.raises(BridgeError) as exc_info:
        service.get(1)
    assert exc_info.value.code == "history_not_found"


def test_history_search_rejects_empty_query_and_invalid_top_k(tmp_path: Path) -> None:
    store, _ = _store_with_two_entries(tmp_path)
    service = HistorySearchService(
        store,
        provider=FakeEmbeddingProvider(),
        hybrid=SearchHybridConfig(rrf_k=60, candidate_multiplier=4, candidate_min=20),
    )
    with pytest.raises(BridgeError) as exc_info:
        service.search("   ")
    assert exc_info.value.code == "invalid_history_query"
    with pytest.raises(BridgeError) as exc_info:
        service.search("x", top_k=51)
    assert exc_info.value.code == "invalid_history_top_k"


def test_large_history_get_can_use_common_whole_result_fallback() -> None:
    entry = HistoryEntryRecord(
        id=1,
        time="2026-09-09T13:24:10",
        cwd="/workspace",
        status="completed",
        file="/workspace/build.py",
        args=(),
        purpose=None,
        source_hash="hash",
        changes=({"type": "parm_changed", "node": 1, "path": "/obj/x", "parm": "p", "before": "a" * 5000, "after": "b"},),
    )

    class Reader:
        def get(self, _history_id: int):
            return entry

    class Estimator:
        def count(self, _text: str) -> int:
            return 9999

    class Resources:
        def __init__(self) -> None:
            self.payloads: list[bytes] = []

        def put_bytes(self, payload: bytes):
            self.payloads.append(payload)
            return SimpleNamespace(semantic_alias="history-result-000")

    resources = Resources()
    logical = HistoryReadService(Reader()).get(1)  # type: ignore[arg-type]
    policy = OutputPolicy(
        inline_max_tokens=256,
        token_estimator=Estimator(),  # type: ignore[arg-type]
        resource_store_factory=lambda: resources,  # type: ignore[arg-type]
    )

    assert policy.present(logical) == {"resource": "history-result-000"}
    stored = json.loads(resources.payloads[0].decode("utf-8"))
    assert stored == logical


def test_history_cli_uses_registered_session_selection(monkeypatch: pytest.MonkeyPatch) -> None:
    selected: list[int | None] = []
    captured: list[dict[str, object]] = []

    def resolve(_settings, session_number):
        selected.append(session_number)
        return object(), SimpleNamespace(identity=ProcessIdentity(3003, "start-3003"))

    class Storage:
        def __init__(self, _paths, **_kwargs):
            pass

        def existing(self, _identity):
            return None

    monkeypatch.setattr(
        history_cmd,
        "load_config",
        lambda: SimpleNamespace(
            houdini=SimpleNamespace(lock_timeout_seconds=120.0),
        ),
    )
    monkeypatch.setattr(history_cmd, "_resolve", resolve)
    monkeypatch.setattr(history_cmd, "HistoryStorageService", Storage)
    monkeypatch.setattr(history_cmd.OutputPolicy, "from_config", classmethod(lambda cls, _settings: object()))
    monkeypatch.setattr(
        history_cmd,
        "emit_result",
        lambda payload, **_kwargs: captured.append(dict(payload)),
    )

    result = CliRunner().invoke(app, ["history", "list", "--session", "3"])

    assert result.exit_code == 0
    assert selected == [3]
    assert captured == [{"entries": []}]


def test_history_invalid_limit_uses_shared_error_envelope() -> None:
    result = CliRunner().invoke(app, ["history", "list", "--limit", "not-an-integer"])

    assert result.exit_code == 1
    assert json.loads(result.stdout) == {
        "error": True,
        "code": "invalid_history_limit",
        "message": "--limit must be an integer.",
    }


def test_history_help_exposes_only_search_get_and_list() -> None:
    result = CliRunner().invoke(app, ["history", "--help"])

    assert result.exit_code == 0
    for command in ("search", "get", "list"):
        assert command in result.stdout
    for removed in ("clear", "reset", "delete", "prune", "rebuild", "checkpoint", "undo", "redo"):
        assert removed not in result.stdout
