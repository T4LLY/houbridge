from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

import numpy as np
import pytest

from houbridge.config import SearchHybridConfig
from houbridge.db.connection import connection_scope
from houbridge.errors import BridgeError
from houbridge.paths import WorkspaceSearchPaths
from houbridge.search.dense import DenseVectorRecord
from houbridge.search.embedding import EmbeddingCoordinator
from houbridge.script_search.documents import module_description, scan_script_documents
from houbridge.script_search.repository import IndexedScript, ScriptIndexRepository
from houbridge.script_search.service import ScriptSearchService


class _Provider:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[str, ...]]] = []

    def encode(self, texts, profile: str) -> np.ndarray:
        self.calls.append((profile, tuple(texts)))
        return np.asarray(
            [[float(index + 1), 1.0] for index, _text in enumerate(texts)],
            dtype=np.float32,
        )


class _DenseIndex:
    def __init__(self) -> None:
        self.records: dict[tuple[str, str], DenseVectorRecord] = {}
        self.removed: list[tuple[str, tuple[str, ...]]] = []
        self.search_calls: list[tuple[str, tuple[str, ...], int, tuple[str, ...]]] = []

    def upsert(self, profile: str, records) -> None:
        for record in records:
            self.records[(profile, record.entry_id)] = record

    def remove(self, profile: str, entry_ids) -> None:
        ids = tuple(entry_ids)
        self.removed.append((profile, ids))
        for entry_id in ids:
            self.records.pop((profile, entry_id), None)

    def search_scored(
        self,
        profile: str,
        query_vector: np.ndarray,
        *,
        namespaces,
        top_k: int,
        entry_ids=None,
    ):
        del query_vector
        allowed = tuple(entry_ids or ())
        self.search_calls.append((profile, tuple(namespaces), top_k, allowed))
        ranked = [
            entry_id
            for entry_id in allowed
            if (profile, entry_id) in self.records
        ][:top_k]
        return [
            (entry_id, 0.30127891 - index * 0.01)
            for index, entry_id in enumerate(ranked)
        ]


def _repository(database: Path) -> ScriptIndexRepository:
    return ScriptIndexRepository(lambda: connection_scope(database))


def _service(
    tmp_path: Path,
    *,
    provider: _Provider | None = None,
    dense: _DenseIndex | None = None,
    profile: str = "code-profile",
    enabled: bool = True,
) -> tuple[ScriptSearchService, _Provider, _DenseIndex]:
    paths = WorkspaceSearchPaths.for_cwd(tmp_path)
    actual_provider = provider or _Provider()
    actual_dense = dense or _DenseIndex()
    service = ScriptSearchService(
        paths=paths,
        embedding_profile=profile,
        enabled=enabled,
        hybrid=SearchHybridConfig(rrf_k=60, candidate_multiplier=8, candidate_min=32),
        embeddings=EmbeddingCoordinator(actual_provider),
        repository=_repository(paths.search_database) if enabled else None,
        dense_index=actual_dense if enabled else None,
    )
    return service, actual_provider, actual_dense


def test_script_search_indexes_exactly_one_document_per_python_file(tmp_path: Path) -> None:
    python_root = tmp_path / ".houbridge" / "python"
    python_root.mkdir(parents=True)
    (python_root / "build.py").write_text(
        '"""Builds preview geometry."""\n\n'
        "def build():\n    return helper()\n\n"
        "def helper():\n    return 1\n\n"
        "class Builder:\n    pass\n",
        encoding="utf-8",
    )
    service, provider, dense = _service(tmp_path)

    result = service.search("create preview", top_k=10)

    assert list(result) == ["hits"]
    assert result["hits"][0]["path"] == ".houbridge/python/build.py"
    assert result["hits"][0]["score"].token == "327.868852"
    assert result["hits"][0]["description"] == "Builds preview geometry."
    assert len(dense.records) == 1
    document_text = provider.calls[0][1][0]
    assert document_text.startswith("Builds preview geometry.\n\n")
    assert "class Builder" in document_text


def test_script_search_omits_description_for_existing_undescribed_script(tmp_path: Path) -> None:
    python_root = tmp_path / ".houbridge" / "python"
    python_root.mkdir(parents=True)
    (python_root / "legacy.py").write_text("def legacy():\n    return 1\n", encoding="utf-8")
    service, _provider, _dense = _service(tmp_path)

    result = service.search("legacy", top_k=10)

    assert result["hits"][0]["path"] == ".houbridge/python/legacy.py"
    assert result["hits"][0]["score"].token == "327.868852"
    assert "description" not in result["hits"][0]


def test_script_search_excludes_top_level_underscore_entries_unless_all(tmp_path: Path) -> None:
    python_root = tmp_path / ".houbridge" / "python"
    local_root = python_root / "_project"
    local_root.mkdir(parents=True)
    (local_root / "probe.py").write_text(
        '"""Inspect project-specific state."""\nLOCAL_ONLY_TOKEN = 1\n',
        encoding="utf-8",
    )
    service, _provider, dense = _service(tmp_path)

    default_result = service.search("LOCAL_ONLY_TOKEN", top_k=10)

    assert default_result == {"hits": []}
    assert len(dense.records) == 1

    all_result = service.search("LOCAL_ONLY_TOKEN", top_k=10, include_all=True)

    assert all_result["hits"][0]["path"] == ".houbridge/python/_project/probe.py"


def test_script_search_invalid_python_remains_file_level_searchable_without_description(
    tmp_path: Path,
) -> None:
    python_root = tmp_path / ".houbridge" / "python"
    python_root.mkdir(parents=True)
    (python_root / "draft.py").write_text(
        '"not a module docstring because parsing fails"\ndef unfinished(\n',
        encoding="utf-8",
    )
    service, provider, dense = _service(tmp_path)

    result = service.search("unfinished", top_k=10)

    assert result["hits"][0]["path"] == ".houbridge/python/draft.py"
    assert result["hits"][0]["score"].token == "327.868852"
    assert "description" not in result["hits"][0]
    assert len(dense.records) == 1
    assert provider.calls[0][1][0].endswith("def unfinished(\n")


def test_script_search_fuses_dense_and_lexical_rankings(tmp_path: Path) -> None:
    python_root = tmp_path / ".houbridge" / "python"
    python_root.mkdir(parents=True)
    (python_root / "a.py").write_text("VALUE = 1\n", encoding="utf-8")
    (python_root / "b.py").write_text(
        "SPECIAL_IDENTIFIER = 2\n",
        encoding="utf-8",
    )
    service, _provider, _dense = _service(tmp_path)

    result = service.search("SPECIAL_IDENTIFIER", top_k=2)

    assert [hit["path"] for hit in result["hits"]] == [
        ".houbridge/python/b.py",
        ".houbridge/python/a.py",
    ]
    assert result["hits"][0]["score"].token == "325.224749"
    assert result["hits"][1]["score"].token == "163.934426"


def test_script_search_backfills_lexical_index_without_reembedding_current_file(
    tmp_path: Path,
) -> None:
    python_root = tmp_path / ".houbridge" / "python"
    python_root.mkdir(parents=True)
    (python_root / "build.py").write_text("BUILD_TOKEN = 1\n", encoding="utf-8")
    paths = WorkspaceSearchPaths.for_cwd(tmp_path)
    document = scan_script_documents(python_root)[0]
    repository = _repository(paths.search_database)
    repository.replace(
        [
            IndexedScript(
                entry_id=document.entry_id,
                relative_path=document.relative_path,
                public_path=document.public_path,
                content_hash=document.content_hash,
                semantic_hash=document.semantic_hash,
                description=document.description,
                embedding_profile="code-profile",
            )
        ]
    )
    provider = _Provider()
    dense = _DenseIndex()
    dense.upsert(
        "code-profile",
        [
            DenseVectorRecord(
                document.entry_id,
                "workspace-script",
                np.asarray([1.0, 1.0], dtype=np.float32),
            )
        ],
    )
    service = ScriptSearchService(
        paths=paths,
        embedding_profile="code-profile",
        enabled=True,
        hybrid=SearchHybridConfig(rrf_k=60, candidate_multiplier=8, candidate_min=32),
        embeddings=EmbeddingCoordinator(provider),
        repository=repository,
        dense_index=dense,
    )

    result = service.search("BUILD_TOKEN", top_k=10)

    assert result["hits"][0]["path"] == ".houbridge/python/build.py"
    assert provider.calls == [("code-profile", ("BUILD_TOKEN",))]
    with sqlite3.connect(paths.search_database) as connection:
        lexical_ids = connection.execute(
            "SELECT entry_id FROM script_lexical_entries"
        ).fetchall()
    assert lexical_ids == [(document.entry_id,)]


def test_script_scan_respects_declared_python_source_encoding(tmp_path: Path) -> None:
    python_root = tmp_path / ".houbridge" / "python"
    python_root.mkdir(parents=True)
    (python_root / "legacy.py").write_bytes(
        b"# -*- coding: cp1252 -*-\n\"\"\"Caf\xe9 builder.\"\"\"\nlabel = 'caf\xe9'\n"
    )

    documents = scan_script_documents(python_root)

    assert len(documents) == 1
    assert documents[0].description == "Café builder."
    assert "café" in documents[0].source


def test_module_description_is_static_normalized_and_optional() -> None:
    source = '"""  Build geometry.\n\n    Uses the current node.  \n"""\nraise RuntimeError("never execute")\n'

    assert module_description(source) == "Build geometry.\n\nUses the current node."
    assert module_description("VALUE = 1\n") is None
    assert module_description('"""   \n"""\n') is None


def test_script_search_reconciles_add_change_and_delete_before_results(tmp_path: Path) -> None:
    python_root = tmp_path / ".houbridge" / "python"
    python_root.mkdir(parents=True)
    first = python_root / "first.py"
    first.write_text("VALUE = 1\n", encoding="utf-8")
    provider = _Provider()
    dense = _DenseIndex()
    service, _provider, _dense = _service(tmp_path, provider=provider, dense=dense)

    first_result = service.search("value", top_k=10)
    first_id = next(iter(dense.records))[1]

    first.unlink()
    second = python_root / "nested" / "second.py"
    second.parent.mkdir()
    second.write_text('"""Second script."""\nVALUE = 2\n', encoding="utf-8")
    second_result = service.search("second", top_k=10)

    assert first_result["hits"][0]["path"] == ".houbridge/python/first.py"
    assert second_result["hits"][0]["path"] == ".houbridge/python/nested/second.py"
    assert any(first_id in removed for _profile, removed in dense.removed)
    assert all(entry_id != first_id for _profile, entry_id in dense.records)

    provider.calls.clear()
    second.write_text('"""Changed second script."""\nVALUE = 3\n', encoding="utf-8")
    changed_result = service.search("changed", top_k=10)

    assert changed_result["hits"][0]["description"] == "Changed second script."
    assert provider.calls[0][1][0].startswith("Changed second script.\n\n")


def test_script_search_reuses_current_file_index_without_reembedding_document(
    tmp_path: Path,
) -> None:
    python_root = tmp_path / ".houbridge" / "python"
    python_root.mkdir(parents=True)
    (python_root / "build.py").write_text("VALUE = 1\n", encoding="utf-8")
    service, provider, _dense = _service(tmp_path)

    service.search("first query", top_k=10)
    provider.calls.clear()
    service.search("second query", top_k=10)

    assert provider.calls == [("code-profile", ("second query",))]


def test_script_index_database_keeps_metadata_but_not_authoritative_source_body(
    tmp_path: Path,
) -> None:
    python_root = tmp_path / ".houbridge" / "python"
    python_root.mkdir(parents=True)
    source = '"""Unique description."""\nSECRET_SOURCE_TOKEN = "only-in-file-body-94731"\n'
    (python_root / "build.py").write_text(source, encoding="utf-8")
    service, _provider, _dense = _service(tmp_path)

    service.search("unique", top_k=10)

    database = tmp_path / ".houbridge" / "search.db"
    with sqlite3.connect(database) as connection:
        columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(script_entries)").fetchall()
        }
        row = connection.execute(
            "SELECT public_path, content_hash, description FROM script_entries"
        ).fetchone()
    assert columns == {
        "entry_id",
        "relative_path",
        "public_path",
        "content_hash",
        "semantic_hash",
        "description",
        "embedding_profile_id",
    }
    assert row is not None
    assert row[0] == ".houbridge/python/build.py"
    assert row[2] == "Unique description."
    assert "source" not in columns
    assert "content" not in columns
    assert b"only-in-file-body-94731" not in database.read_bytes()


def test_empty_workspace_returns_no_hits_without_dense_query(tmp_path: Path) -> None:
    service, provider, dense = _service(tmp_path)

    result = service.search("nothing", top_k=10)

    assert result == {"hits": []}
    assert provider.calls == []
    assert dense.search_calls == []


def test_disabled_script_database_does_not_create_workspace_database(tmp_path: Path) -> None:
    paths = WorkspaceSearchPaths.for_cwd(tmp_path)
    service = ScriptSearchService(
        paths=paths,
        embedding_profile="code-profile",
        enabled=False,
        hybrid=SearchHybridConfig(rrf_k=60, candidate_multiplier=8, candidate_min=32),
    )

    with pytest.raises(BridgeError) as caught:
        service.search("anything")

    assert caught.value.code == "local_script_database_disabled"
    assert not paths.search_database.exists()
    assert not paths.workspace_directory.exists()


def test_embedding_profile_change_replaces_derived_vector_namespace(tmp_path: Path) -> None:
    python_root = tmp_path / ".houbridge" / "python"
    python_root.mkdir(parents=True)
    (python_root / "build.py").write_text("VALUE = 1\n", encoding="utf-8")
    dense = _DenseIndex()
    first, _provider, _dense = _service(tmp_path, dense=dense, profile="profile-a")
    first.search("first", top_k=10)
    first_entry = next(iter(dense.records))[1]

    second, _provider, _dense = _service(tmp_path, dense=dense, profile="profile-b")
    second.search("second", top_k=10)

    assert ("profile-a", (first_entry,)) in dense.removed
    assert ("profile-a", first_entry) not in dense.records
    assert ("profile-b", first_entry) in dense.records


def test_script_search_dense_only_keeps_the_only_eligible_file_with_hidden_vectors(
    tmp_path: Path,
) -> None:
    python_root = tmp_path / ".houbridge" / "python"
    python_root.mkdir(parents=True)
    hidden_files = []
    for index in range(8):
        path = python_root / f"_hidden_{index}.py"
        path.write_text(f"HIDDEN_VALUE_{index} = {index}\n", encoding="utf-8")
        hidden_files.append(path)
    eligible = python_root / "visible.py"
    eligible.write_text("ELIGIBLE_VALUE = 1\n", encoding="utf-8")

    paths = WorkspaceSearchPaths.for_cwd(tmp_path)
    service = ScriptSearchService(
        paths=paths,
        embedding_profile="code-profile",
        enabled=True,
        hybrid=SearchHybridConfig(rrf_k=60, candidate_multiplier=1, candidate_min=1),
        provider=_Provider(),
    )
    query = "UNMATCHED_QUERY_TOKEN"

    default_result = service.search(query, top_k=1)
    assert [hit["path"] for hit in default_result["hits"]] == [
        ".houbridge/python/visible.py"
    ]

    all_result = service.search(query, top_k=1, include_all=True)
    assert all_result["hits"][0]["path"].startswith(".houbridge/python/_hidden_")

    second_eligible = python_root / "visible_second.py"
    second_eligible.write_text("SECOND_ELIGIBLE_VALUE = 2\n", encoding="utf-8")
    assert service.search(query, top_k=1)["hits"][0]["path"].startswith(
        ".houbridge/python/visible"
    )

    for path in hidden_files:
        path.unlink()
    no_hidden_result = service.search(query, top_k=1)
    assert no_hidden_result["hits"][0]["path"].startswith(".houbridge/python/visible")
