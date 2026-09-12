from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from houbridge.resource.dump import ResourceDumper
from houbridge.resource.store import ResourceStore
from houbridge.semantic_id import SemanticBase
from houbridge.temporary_artifact import TemporaryArtifactService


class _FixedSemanticGenerator:
    def generate(self, _text: str, *, fallback_stem: str) -> SemanticBase:
        return SemanticBase(prefix="resource-dump-test", tags=("resource", "dump", "test"))


class _Clock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value


def _store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    clock: _Clock | None = None,
) -> ResourceStore:
    import houbridge.resource.classifier as classifier

    monkeypatch.setattr(classifier.filetype, "guess", lambda _payload: None)
    return ResourceStore(
        tmp_path / "data" / "resources.db",
        semantic_generator=_FixedSemanticGenerator(),
        now=clock,
    )


def test_dump_json_preserves_exact_stored_bytes_and_mime_extension(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path, monkeypatch)
    payload = b'{ "a" : 1 }\n'
    resource = store.put_bytes(payload)
    dumper = ResourceDumper(
        store,
        TemporaryArtifactService(temp_root=tmp_path / "temp"),
        ttl_hours=72,
    )

    result = dumper.dump(resource.semantic_alias)
    path = Path(result["path"])

    assert path.suffix == ".json"
    assert path.read_bytes() == payload
    assert set(result) == {"path"}


def test_dump_uses_bin_when_stored_mime_has_no_extension(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path, monkeypatch)
    resource = store.put_bytes(b"payload")
    with sqlite3.connect(store.database) as connection:
        connection.execute(
            "UPDATE resources SET mime = ? WHERE canonical_id = ?",
            ("application/x-houbridge-no-extension", resource.canonical_id),
        )
    dumper = ResourceDumper(
        store,
        TemporaryArtifactService(temp_root=tmp_path / "temp"),
        ttl_hours=72,
    )

    path = Path(dumper.dump(resource.semantic_alias)["path"])

    assert path.suffix == ".bin"
    assert path.read_bytes() == b"payload"


def test_dump_cleanup_uses_resource_ttl_without_refreshing_source_retention(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    start = datetime(2026, 9, 11, 0, 0, tzinfo=timezone.utc)
    clock = _Clock(start)
    store = _store(tmp_path, monkeypatch, clock=clock)
    resource = store.put_text("source")
    original_expiry = resource.expires_at
    artifacts = TemporaryArtifactService(temp_root=tmp_path / "temp")
    stale = artifacts.publish_bytes(
        b"stale",
        namespace="resource",
        stem="resource",
        extension=".txt",
    )
    now_timestamp = start.timestamp() + (73 * 60 * 60)
    os.utime(stale, (start.timestamp(), start.timestamp()))
    dumper = ResourceDumper(
        store,
        artifacts,
        ttl_hours=72,
        now_timestamp=lambda: now_timestamp,
    )

    result = dumper.dump(resource.semantic_alias)

    assert not stale.exists()
    assert Path(result["path"]).read_bytes() == b"source"
    assert store.get(resource.semantic_alias).expires_at == original_expiry


def test_dump_png_uses_classifier_mime_extension_and_exact_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import houbridge.resource.classifier as classifier

    class _Detected:
        mime = "image/png"

    monkeypatch.setattr(classifier.filetype, "guess", lambda _payload: _Detected())
    store = ResourceStore(
        tmp_path / "data" / "resources.db",
        semantic_generator=_FixedSemanticGenerator(),
    )
    payload = b"\x89PNG\r\n\x1a\nexact"
    resource = store.put_bytes(payload)
    dumper = ResourceDumper(
        store,
        TemporaryArtifactService(temp_root=tmp_path / "temp"),
        ttl_hours=72,
    )

    path = Path(dumper.dump(resource.semantic_alias)["path"])

    assert path.suffix == ".png"
    assert path.read_bytes() == payload
