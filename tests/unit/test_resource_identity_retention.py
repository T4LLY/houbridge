from __future__ import annotations

import hashlib
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from houbridge.resource.store import ResourceStore
from houbridge.semantic_id import SemanticBase


class FixedSemanticGenerator:
    def __init__(self, prefix: str = "node-graph-python") -> None:
        self.prefix = prefix
        self.seen_text: list[str] = []

    def generate(self, text: str, *, fallback_stem: str) -> SemanticBase:
        self.seen_text.append(text)
        tags = tuple(self.prefix.split("-"))
        return SemanticBase(prefix=self.prefix, tags=tags)


class Clock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value


def make_store(
    database: Path,
    *,
    generator: FixedSemanticGenerator | None = None,
    clock: Clock | None = None,
    ttl_hours: int = 72,
) -> ResourceStore:
    return ResourceStore(
        database,
        ttl_hours=ttl_hours,
        semantic_generator=generator or FixedSemanticGenerator(),
        now=clock,
    )


def test_alias_ordinal_is_prefix_local_and_zero_padded(tmp_path: Path, monkeypatch) -> None:
    import houbridge.resource.classifier as classifier

    monkeypatch.setattr(classifier.filetype, "guess", lambda _payload: None)
    store = make_store(tmp_path / "resources.db")

    first = store.put_text("first")
    second = store.put_text("second")

    assert first.semantic_alias == "node-graph-python000"
    assert second.semantic_alias == "node-graph-python001"


def test_alias_ordinal_expands_beyond_three_digits(tmp_path: Path, monkeypatch) -> None:
    import houbridge.resource.classifier as classifier

    monkeypatch.setattr(classifier.filetype, "guess", lambda _payload: None)
    database = tmp_path / "resources.db"
    store = make_store(database)
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            INSERT INTO resource_semantic_aliases(
                canonical_id, semantic_alias, prefix, ordinal, tags_json
            ) VALUES (?, ?, ?, ?, ?)
            """,
            ("seed", "node-graph-python999", "node-graph-python", 999, "[]"),
        )

    resource = store.put_text("ordinal 1000")

    assert resource.semantic_alias == "node-graph-python1000"


def test_same_payload_keeps_alias_and_write_refreshes_retention(tmp_path: Path, monkeypatch) -> None:
    import houbridge.resource.classifier as classifier

    monkeypatch.setattr(classifier.filetype, "guess", lambda _payload: None)
    start = datetime(2026, 9, 11, 0, 0, tzinfo=timezone.utc)
    clock = Clock(start)
    generator = FixedSemanticGenerator()
    store = make_store(tmp_path / "resources.db", generator=generator, clock=clock)

    first = store.put_text("same")
    clock.value = start + timedelta(hours=24)
    second = store.put_text("same")

    assert second.canonical_id == first.canonical_id
    assert second.semantic_alias == first.semantic_alias
    assert second.created_at == first.created_at
    assert datetime.fromisoformat(second.expires_at) == start + timedelta(hours=96)
    assert generator.seen_text == ["same"]


def test_reads_do_not_extend_retention(tmp_path: Path, monkeypatch) -> None:
    import houbridge.resource.classifier as classifier

    monkeypatch.setattr(classifier.filetype, "guess", lambda _payload: None)
    start = datetime(2026, 9, 11, 0, 0, tzinfo=timezone.utc)
    clock = Clock(start)
    store = make_store(tmp_path / "resources.db", clock=clock)
    resource = store.put_text("read only")
    original_expiry = resource.expires_at
    clock.value = start + timedelta(hours=48)

    assert store.get(resource.semantic_alias).expires_at == original_expiry
    assert store.get_bytes(resource.semantic_alias) == b"read only"
    assert store.get(resource.canonical_id).expires_at == original_expiry


def test_cleanup_preserves_alias_and_ordinal_reservation(tmp_path: Path, monkeypatch) -> None:
    import houbridge.resource.classifier as classifier

    monkeypatch.setattr(classifier.filetype, "guess", lambda _payload: None)
    start = datetime(2026, 9, 11, 0, 0, tzinfo=timezone.utc)
    clock = Clock(start)
    generator = FixedSemanticGenerator()
    store = make_store(tmp_path / "resources.db", generator=generator, clock=clock)
    first = store.put_text("expires")

    clock.value = start + timedelta(hours=73)
    assert store.cleanup_expired() == 1
    assert store.get(first.semantic_alias) is None
    assert store.resolve_canonical_id(first.semantic_alias) == first.canonical_id

    restored = store.put_text("expires")
    next_resource = store.put_text("different")

    assert restored.semantic_alias == first.semantic_alias
    assert next_resource.semantic_alias == "node-graph-python001"
    assert generator.seen_text == ["expires", "different"]


def test_semantic_text_uses_binary_mime_and_does_not_decode_payload(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import houbridge.resource.classifier as classifier

    class Detected:
        mime = "image/png"

    monkeypatch.setattr(classifier.filetype, "guess", lambda _payload: Detected())
    generator = FixedSemanticGenerator()
    store = make_store(tmp_path / "resources.db", generator=generator)

    store.put_bytes(b"\xff\xfe\x00PNG")

    assert generator.seen_text == ["image/png"]


def test_semantic_text_uses_mime_for_blank_decoded_text(tmp_path: Path, monkeypatch) -> None:
    import houbridge.resource.classifier as classifier

    monkeypatch.setattr(classifier.filetype, "guess", lambda _payload: None)
    generator = FixedSemanticGenerator()
    store = make_store(tmp_path / "resources.db", generator=generator)

    store.put_text("   \n")

    assert generator.seen_text == ["text/plain"]


def test_lookup_accepts_semantic_alias_and_canonical_hash(tmp_path: Path, monkeypatch) -> None:
    import houbridge.resource.classifier as classifier

    monkeypatch.setattr(classifier.filetype, "guess", lambda _payload: None)
    store = make_store(tmp_path / "resources.db")
    resource = store.put_text("lookup")

    assert store.get(resource.semantic_alias) == resource
    assert store.get(resource.canonical_id) == resource
    assert store.get_bytes(resource.semantic_alias) == b"lookup"
    assert store.resolve_canonical_id(resource.semantic_alias) == resource.canonical_id


def test_concurrent_same_payload_commits_one_alias(tmp_path: Path, monkeypatch) -> None:
    import houbridge.resource.classifier as classifier

    monkeypatch.setattr(classifier.filetype, "guess", lambda _payload: None)
    database = tmp_path / "resources.db"
    store = make_store(database)

    with ThreadPoolExecutor(max_workers=8) as executor:
        resources = list(executor.map(lambda _i: store.put_text("same concurrent"), range(8)))

    assert {resource.semantic_alias for resource in resources} == {"node-graph-python000"}
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM resources").fetchone() == (1,)
        assert connection.execute(
            "SELECT COUNT(*) FROM resource_semantic_aliases"
        ).fetchone() == (1,)


def test_concurrent_distinct_payloads_never_reuse_prefix_ordinal(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import houbridge.resource.classifier as classifier

    monkeypatch.setattr(classifier.filetype, "guess", lambda _payload: None)
    database = tmp_path / "resources.db"
    store = make_store(database)

    with ThreadPoolExecutor(max_workers=8) as executor:
        resources = list(executor.map(lambda i: store.put_text(f"payload {i}"), range(8)))

    aliases = {resource.semantic_alias for resource in resources}
    assert len(aliases) == 8
    assert aliases == {f"node-graph-python{i:03d}" for i in range(8)}


def test_resource_schema_contains_only_resource_metadata(tmp_path: Path) -> None:
    database = tmp_path / "resources.db"
    make_store(database)

    with sqlite3.connect(database) as connection:
        resource_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(resources)")
        }
        alias_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(resource_semantic_aliases)")
        }

    assert resource_columns == {
        "canonical_id",
        "content_class",
        "mime",
        "byte_size",
        "token_count",
        "created_at",
        "expires_at",
        "payload",
    }
    assert alias_columns == {
        "canonical_id",
        "semantic_alias",
        "prefix",
        "ordinal",
        "tags_json",
    }
    assert all("task" not in column and "execution" not in column for column in alias_columns)


def test_canonical_identity_remains_sha256_of_exact_payload(tmp_path: Path, monkeypatch) -> None:
    import houbridge.resource.classifier as classifier

    monkeypatch.setattr(classifier.filetype, "guess", lambda _payload: None)
    payload = b"exact bytes\x00are binary"
    store = make_store(tmp_path / "resources.db")

    resource = store.put_bytes(payload)

    assert resource.canonical_id == hashlib.sha256(payload).hexdigest()


def test_successful_write_cleans_at_expiry_without_losing_aliases(
    tmp_path: Path, monkeypatch
) -> None:
    import houbridge.resource.classifier as classifier

    monkeypatch.setattr(classifier.filetype, "guess", lambda _payload: None)
    start = datetime(2026, 9, 11, 0, 0, tzinfo=timezone.utc)
    clock = Clock(start)
    generator = FixedSemanticGenerator()
    database = tmp_path / "resources.db"
    store = make_store(database, generator=generator, clock=clock)

    expired = store.put_text("expires at boundary")
    also_expired = store.put_text("another expires at boundary")
    clock.value = start + timedelta(hours=24)
    active = store.put_text("not expired")
    clock.value = start + timedelta(hours=72)

    assert store.get(expired.semantic_alias).expires_at == expired.expires_at
    assert store.get_bytes(expired.canonical_id) == b"expires at boundary"
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM resources WHERE canonical_id = ?",
            (expired.canonical_id,),
        ).fetchone() == (1,)

    restored = store.put_text("expires at boundary")

    assert store.get(expired.semantic_alias) == restored
    assert store.get(also_expired.semantic_alias) is None
    assert store.get(active.semantic_alias) == active
    assert datetime.fromisoformat(restored.expires_at) == clock.value + timedelta(
        hours=72
    )
    assert store.resolve_canonical_id(expired.semantic_alias) == expired.canonical_id
    written = store.put_text("boundary write")
    following = store.put_text("after restore")
    assert written.semantic_alias == "node-graph-python003"
    assert following.semantic_alias == "node-graph-python004"
    assert generator.seen_text == [
        "expires at boundary",
        "another expires at boundary",
        "not expired",
        "boundary write",
        "after restore",
    ]


def test_failed_write_rolls_back_expiry_cleanup_and_alias_allocation(
    tmp_path: Path, monkeypatch
) -> None:
    import houbridge.resource.classifier as classifier

    monkeypatch.setattr(classifier.filetype, "guess", lambda _payload: None)
    start = datetime(2026, 9, 11, 0, 0, tzinfo=timezone.utc)
    clock = Clock(start)
    database = tmp_path / "resources.db"
    store = make_store(database, clock=clock)
    expired = store.put_text("expired")
    clock.value = start + timedelta(hours=72)

    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            CREATE TRIGGER reject_expiry_cleanup
            BEFORE DELETE ON resources
            BEGIN
                SELECT RAISE(ABORT, 'forced cleanup failure');
            END
            """
        )

    with pytest.raises(sqlite3.IntegrityError, match="forced cleanup failure"):
        store.put_text("attempted write")

    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM resources").fetchone() == (1,)
        assert connection.execute(
            "SELECT COUNT(*) FROM resource_semantic_aliases"
        ).fetchone() == (1,)
    assert store.get(expired.semantic_alias) is not None
    assert store.resolve_canonical_id("node-graph-python001") is None

    with sqlite3.connect(database) as connection:
        connection.execute("DROP TRIGGER reject_expiry_cleanup")

    written = store.put_text("attempted write")
    assert written.semantic_alias == "node-graph-python001"
    assert store.get(expired.semantic_alias) is None
