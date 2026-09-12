from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from houbridge.output.tokens import FallbackTokenEstimator
from houbridge.resource.store import ResourceStore


def test_store_persists_exact_payload_bytes_in_global_database(tmp_path: Path, monkeypatch) -> None:
    import houbridge.resource.classifier as classifier

    monkeypatch.setattr(classifier.filetype, "guess", lambda _payload: None)
    database = tmp_path / "global" / "resources.db"
    store = ResourceStore(database)
    payload = b"exact payload\n"

    resource = store.put_bytes(payload)

    assert resource.canonical_id == hashlib.sha256(payload).hexdigest()
    assert store.get_bytes(resource.canonical_id) == payload
    assert not (database.parent / "resources").exists()
    with sqlite3.connect(database) as connection:
        stored = connection.execute(
            "SELECT canonical_id, content_class, mime, byte_size, token_count, payload FROM resources"
        ).fetchone()
    assert stored == (
        resource.canonical_id,
        "text",
        "text/plain",
        len(payload),
        FallbackTokenEstimator().count(payload.decode("utf-8")),
        payload,
    )


def test_store_deduplicates_identical_payload_across_working_directories(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import houbridge.resource.classifier as classifier

    monkeypatch.setattr(classifier.filetype, "guess", lambda _payload: None)
    database = tmp_path / "global" / "resources.db"
    workspace_a = tmp_path / "workspace-a"
    workspace_b = tmp_path / "workspace-b"
    workspace_a.mkdir()
    workspace_b.mkdir()
    payload = b"shared resource"

    monkeypatch.chdir(workspace_a)
    first = ResourceStore(database).put_bytes(payload)
    monkeypatch.chdir(workspace_b)
    second = ResourceStore(database).put_bytes(payload)

    assert first.canonical_id == second.canonical_id
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM resources").fetchone() == (1,)


def test_store_does_not_put_task_or_history_state_in_resources_database(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import houbridge.resource.classifier as classifier

    monkeypatch.setattr(classifier.filetype, "guess", lambda _payload: None)
    database = tmp_path / "resources.db"
    ResourceStore(database).put_text("hello")

    with sqlite3.connect(database) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }

    assert tables == {"resources"}


def test_binary_resource_has_no_token_count(tmp_path: Path, monkeypatch) -> None:
    import houbridge.resource.classifier as classifier

    class Detected:
        mime = "image/png"

    monkeypatch.setattr(classifier.filetype, "guess", lambda _payload: Detected())
    store = ResourceStore(tmp_path / "resources.db")

    resource = store.put_bytes(b"\x89PNG\r\n\x1a\n")

    assert resource.content_class == "binary"
    assert resource.mime == "image/png"
    assert resource.token_count is None


def test_put_json_uses_compact_sorted_utf8_serialization(tmp_path: Path, monkeypatch) -> None:
    import houbridge.resource.classifier as classifier

    monkeypatch.setattr(classifier.filetype, "guess", lambda _payload: None)
    store = ResourceStore(tmp_path / "resources.db")

    resource = store.put_json({"z": "日本語", "a": 1})
    expected = json.dumps(
        {"z": "日本語", "a": 1},
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")

    assert resource.content_class == "json"
    assert resource.mime == "application/json"
    assert store.get_bytes(resource.canonical_id) == expected
    assert resource.canonical_id == hashlib.sha256(expected).hexdigest()


def test_resource_schema_has_no_filesystem_payload_path(tmp_path: Path) -> None:
    database = tmp_path / "resources.db"
    ResourceStore(database)

    with sqlite3.connect(database) as connection:
        columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(resources)").fetchall()
        }

    assert "payload" in columns
    assert "path" not in columns


def test_store_from_config_uses_same_global_database_from_different_cwds(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from dataclasses import replace

    import houbridge.resource.classifier as classifier
    from houbridge.config import StorageConfig, load_config

    monkeypatch.setattr(classifier.filetype, "guess", lambda _payload: None)
    workspace_a = tmp_path / "workspace-a"
    workspace_b = tmp_path / "workspace-b"
    workspace_a.mkdir()
    workspace_b.mkdir()
    config = load_config(tmp_path / "config.toml", cwd=workspace_a)
    data_dir = tmp_path / "global-data"
    config = replace(config, storage=StorageConfig(data_dir=data_dir))

    monkeypatch.chdir(workspace_a)
    first = ResourceStore.from_config(config)
    stored = first.put_text("global payload")

    monkeypatch.chdir(workspace_b)
    second = ResourceStore.from_config(config)

    assert first.database == data_dir / "resources.db"
    assert second.database == first.database
    assert second.get_bytes(stored.canonical_id) == b"global payload"
