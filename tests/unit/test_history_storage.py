from __future__ import annotations

import hashlib
import sqlite3
import threading
from pathlib import Path

import numpy as np
import pytest

from houbridge.errors import BridgeError
from houbridge.history import HistoryStorageService, HistoryStore, history_session_key
from houbridge.history.reader import HistoryReader
from houbridge.paths import GlobalDataPaths
from houbridge.process_coordination import ProcessIdentity


class FakeEmbeddingProvider:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[str, ...]]] = []

    def encode(self, texts, profile: str) -> np.ndarray:
        self.calls.append((profile, tuple(texts)))
        return np.asarray([[1.0, 2.0, 3.0] for _ in texts], dtype=np.float32)


def test_history_path_isolated_by_exact_process_incarnation(tmp_path: Path) -> None:
    paths = GlobalDataPaths.from_data_dir(tmp_path / "data")
    service = HistoryStorageService(paths)
    first = ProcessIdentity(1200, "start-a")
    reused_pid = ProcessIdentity(1200, "start-b")
    other = ProcessIdentity(1300, "start-a")

    assert history_session_key(first) != history_session_key(reused_pid)
    assert history_session_key(first) != history_session_key(other)
    assert service.database_for(first) != service.database_for(reused_pid)
    assert service.database_for(first).parent.parent == paths.history_directory


def test_disabled_history_does_not_initialize_database_or_embedding(tmp_path: Path) -> None:
    provider = FakeEmbeddingProvider()
    paths = GlobalDataPaths.from_data_dir(tmp_path / "data")
    service = HistoryStorageService(paths, embedding_provider=provider)
    identity = ProcessIdentity(1200, "start-a")

    storage = service.for_recording(
        identity,
        enabled=False,
        requested_code_profile="profile-a",
    )

    assert storage is None
    assert not service.database_for(identity).exists()
    assert provider.calls == []


def test_session_profile_is_fixed_by_first_history_initialization(tmp_path: Path) -> None:
    provider = FakeEmbeddingProvider()
    database = tmp_path / "history.db"
    store = HistoryStore(database, embedding_provider=provider)

    assert store.initialize("profile-a") == "profile-a"
    assert store.initialize("profile-b") == "profile-a"
    assert store.code_profile() == "profile-a"


def test_source_embedding_is_reused_without_persisting_source_body(tmp_path: Path) -> None:
    provider = FakeEmbeddingProvider()
    database = tmp_path / "history.db"
    store = HistoryStore(database, embedding_provider=provider)
    source = "SECRET_HISTORY_SOURCE_SENTINEL = 'never persist me'\n"
    expected_hash = hashlib.sha256(source.encode("utf-8")).hexdigest()

    first = store.embed_source(source, requested_code_profile="profile-a")
    second = store.embed_source(source, requested_code_profile="profile-b")

    assert first.source_hash == expected_hash
    assert second.source_hash == expected_hash
    assert first.profile == second.profile == "profile-a"
    assert provider.calls == [("profile-a", (source,))]

    with sqlite3.connect(database) as connection:
        row = connection.execute(
            """
            SELECT embedding_profile_id, content_hash, dimensions
            FROM history_source_embeddings
            """
        ).fetchone()
        columns = {
            column[1]
            for table in ("history_entries", "history_changes", "history_source_embeddings")
            for column in connection.execute(f"PRAGMA table_info({table})").fetchall()
        }
    assert row == ("profile-a", expected_hash, 3)
    assert "source" not in columns
    assert source.encode("utf-8") not in database.read_bytes()


def test_history_ids_are_monotonic_within_one_session_database(tmp_path: Path) -> None:
    store = HistoryStore(tmp_path / "history.db", embedding_provider=FakeEmbeddingProvider())

    ids = [store.allocate_id(requested_code_profile="profile-a") for _ in range(3)]

    assert ids == [1, 2, 3]


def test_history_schema_keeps_entries_changes_search_and_metadata_in_one_database(
    tmp_path: Path,
) -> None:
    database = tmp_path / "history.db"
    store = HistoryStore(database, embedding_provider=FakeEmbeddingProvider())
    store.initialize("profile-a")

    with sqlite3.connect(database) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
            ).fetchall()
        }
        change_columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(history_changes)").fetchall()
        }

    assert {
        "history_metadata",
        "history_id_sequence",
        "history_entries",
        "history_changes",
        "history_source_embeddings",
        "history_vector_profiles",
        "history_lexical_entries",
        "history_lexical_fts",
    } <= tables
    assert "node_session_id" in change_columns
    assert not (tmp_path / "history-source").exists()

def test_history_reader_does_not_recreate_database_after_scene_reset(tmp_path: Path) -> None:
    database = tmp_path / "history.db"
    store = HistoryStore(database, embedding_provider=FakeEmbeddingProvider())
    store.initialize("profile-a")
    reader = HistoryReader(database)

    database.unlink()

    assert reader.get(1) is None
    assert reader.list(10) == []
    assert reader.all_for_search() == []
    assert not database.exists()



def test_history_connection_wait_is_bounded_by_configured_lock_timeout(tmp_path: Path) -> None:
    database = tmp_path / "history.db"
    holder = HistoryStore(
        database,
        embedding_provider=FakeEmbeddingProvider(),
        lock_timeout_seconds=1.0,
    )
    contender = HistoryStore(
        database,
        embedding_provider=FakeEmbeddingProvider(),
        lock_timeout_seconds=0.05,
    )

    entered = threading.Event()
    release = threading.Event()

    def hold() -> None:
        with holder._connect() as connection:
            connection.execute("CREATE TABLE held(value INTEGER)")
            entered.set()
            assert release.wait(timeout=2)

    thread = threading.Thread(target=hold)
    thread.start()
    assert entered.wait(timeout=2)

    try:
        with pytest.raises(BridgeError) as caught:
            contender.initialize("profile-a")
        assert caught.value.code == "history_lock_timeout"
    finally:
        release.set()
        thread.join(timeout=2)
    assert not thread.is_alive()
