from __future__ import annotations

import re
import sqlite3
from pathlib import Path

import pytest

from houbridge.errors import BridgeError
from houbridge.output.tokens import FallbackTokenEstimator
from houbridge.resource.reader import (
    ResourceReader,
    _JsonSpanParser,
    _substring_matches,
)
from houbridge.resource.store import ResourceStore
from houbridge.semantic_id import SemanticBase


class _FixedSemanticGenerator:
    def generate(self, _text: str, *, fallback_stem: str) -> SemanticBase:
        return SemanticBase(
            prefix="resource-test-payload", tags=("resource", "test", "payload")
        )


def _store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ResourceStore:
    import houbridge.resource.classifier as classifier

    monkeypatch.setattr(classifier.filetype, "guess", lambda _payload: None)
    return ResourceStore(
        tmp_path / "resources.db",
        semantic_generator=_FixedSemanticGenerator(),
    )


def _reader(
    store: ResourceStore,
    *,
    inline_limit_bytes: int = 16384,
    search_limit: int = 10,
) -> ResourceReader:
    return ResourceReader(
        store,
        inline_limit_bytes=inline_limit_bytes,
        search_limit=search_limit,
    )


def test_info_uses_persisted_content_class_for_exact_size_field(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path, monkeypatch)
    text = store.put_text("hello")
    binary = store.put_bytes(b"\xff\xfe\x00")
    reader = _reader(store)

    assert reader.info(text.semantic_alias) == {
        "mime": "text/plain",
        "tokens": FallbackTokenEstimator().count("hello"),
    }
    assert reader.info(binary.semantic_alias) == {
        "mime": "application/octet-stream",
        "bytes": 3,
    }


def test_get_returns_text_json_and_binary_contracts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path, monkeypatch)
    text = store.put_text("hello")
    structured = store.put_bytes(b'{"foo":"bar"}')
    binary = store.put_bytes(b"\xff\xfe\x00")
    reader = _reader(store)

    assert reader.get(text.semantic_alias) == {"truncated": False, "result": "hello"}
    assert reader.get(structured.semantic_alias) == {
        "truncated": False,
        "result": {"foo": "bar"},
    }
    assert reader.get(binary.semantic_alias) == {"truncated": False, "binary": True}


def test_get_soft_limit_can_only_be_bypassed_by_full(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path, monkeypatch)
    resource = store.put_text("abcdefgh")
    reader = _reader(store, inline_limit_bytes=4)

    assert reader.get(resource.semantic_alias) == {"truncated": True, "next_offset": 0}
    assert reader.get(resource.semantic_alias, full=True) == {
        "truncated": False,
        "result": "abcdefgh",
    }


def test_get_full_still_respects_final_serialized_json_hard_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path, monkeypatch)
    # Newlines occupy one payload byte but two bytes after JSON escaping, so this
    # exercises the final serialized response boundary rather than raw payload size.
    resource = store.put_text("\n" * 33000)
    reader = _reader(store, inline_limit_bytes=1)

    assert reader.get(resource.semantic_alias, full=True) == {
        "truncated": True,
        "next_offset": 0,
    }


def test_slice_uses_character_offsets_and_never_splits_utf8(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path, monkeypatch)
    resource = store.put_text("A" + ("界" * 6000) + "Z")
    reader = _reader(store)

    result = reader.slice(resource.semantic_alias, offset=1, limit=16384)

    chunk = result["result"]
    assert isinstance(chunk, str)
    assert len(chunk.encode("utf-8")) <= 16384
    assert chunk == "界" * 5461
    assert result["truncated"] is True
    assert result["next_offset"] == 5462


def test_slice_rejects_invalid_offset_limit_and_binary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path, monkeypatch)
    text = store.put_text("hello")
    binary = store.put_bytes(b"\xff\xfe\x00")
    reader = _reader(store)

    with pytest.raises(BridgeError) as exc_info:
        reader.slice(text.semantic_alias, offset=-1, limit=1)
    assert exc_info.value.code == "invalid_slice"

    with pytest.raises(BridgeError) as exc_info:
        reader.slice(text.semantic_alias, offset=0, limit=16385)
    assert exc_info.value.code == "resource_slice_limit_exceeded"

    with pytest.raises(BridgeError) as exc_info:
        reader.slice(binary.semantic_alias, offset=0, limit=1)
    assert exc_info.value.code == "resource_not_text"


def test_search_is_literal_case_insensitive_bounded_and_character_offset_based(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path, monkeypatch)
    resource = store.put_text("界Alpha alpha ALPHA")
    reader = _reader(store, search_limit=2)

    first = reader.search(resource.semantic_alias, "alpha")
    second = reader.search(resource.semantic_alias, "alpha", offset=2)

    assert first == {
        "hit_count": 3,
        "hits": [{"offset": 1}, {"offset": 7}],
        "truncated": True,
    }
    assert second == {"hit_count": 3, "hits": [{"offset": 13}]}


def test_search_json_reports_narrowest_value_path_and_key_value_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path, monkeypatch)
    text = '{"nodes":[{"name":"Alpha","meta":{"AlphaKey":"value"}}]}'
    resource = store.put_bytes(text.encode("utf-8"))
    reader = _reader(store, search_limit=10)

    result = reader.search(resource.semantic_alias, "Alpha")

    assert result["hit_count"] == 2
    hits = result["hits"]
    assert isinstance(hits, list)
    assert hits[0]["path"] == "$.nodes[0].name"
    assert hits[0]["offset"] == text.index("Alpha")
    assert hits[0]["tokens"] == FallbackTokenEstimator().count('"Alpha"')
    assert hits[1]["path"] == "$.nodes[0].meta.AlphaKey"
    assert hits[1]["offset"] == text.index("AlphaKey")
    assert hits[1]["tokens"] == FallbackTokenEstimator().count('"value"')


def test_json_structural_search_rejects_corrupted_json_class_payload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path, monkeypatch)
    resource = store.put_bytes(b'{"valid":true}')
    with sqlite3.connect(store.database) as connection:
        connection.execute(
            "UPDATE resources SET payload = ?, byte_size = ? WHERE canonical_id = ?",
            (b'{"broken":', len(b'{"broken":'), resource.canonical_id),
        )
    reader = _reader(store)

    with pytest.raises(BridgeError) as exc_info:
        reader.search(resource.semantic_alias, "broken")

    assert exc_info.value.code == "invalid_json_resource"


def test_search_rejects_empty_query_negative_offset_and_binary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path, monkeypatch)
    text = store.put_text("hello")
    binary = store.put_bytes(b"\xff\xfe\x00")
    reader = _reader(store)

    with pytest.raises(BridgeError) as exc_info:
        reader.search(text.semantic_alias, "")
    assert exc_info.value.code == "empty_query"

    with pytest.raises(BridgeError) as exc_info:
        reader.search(text.semantic_alias, "x", offset=-1)
    assert exc_info.value.code == "invalid_search_offset"

    with pytest.raises(BridgeError) as exc_info:
        reader.search(binary.semantic_alias, "x")
    assert exc_info.value.code == "resource_not_text"


def test_missing_or_empty_resource_id_fails_explicitly(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path, monkeypatch)
    reader = _reader(store)

    with pytest.raises(BridgeError) as exc_info:
        reader.info("missing-resource")
    assert exc_info.value.code == "resource_not_found"

    with pytest.raises(BridgeError) as exc_info:
        reader.get("")
    assert exc_info.value.code == "invalid_resource_id"


def test_get_rejects_corrupted_json_class_payload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path, monkeypatch)
    resource = store.put_bytes(b'{"valid":true}')
    with sqlite3.connect(store.database) as connection:
        connection.execute(
            "UPDATE resources SET payload = ?, byte_size = ? WHERE canonical_id = ?",
            (b'{"broken":', len(b'{"broken":'), resource.canonical_id),
        )
    reader = _reader(store)

    with pytest.raises(BridgeError) as exc_info:
        reader.get(resource.semantic_alias, full=True)

    assert exc_info.value.code == "invalid_json_resource"


def test_slice_at_end_omits_continuation_fields(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path, monkeypatch)
    resource = store.put_text("hello")
    reader = _reader(store)

    assert reader.slice(resource.semantic_alias, offset=2, limit=10) == {
        "result": "llo"
    }


def test_search_limit_never_exposes_more_than_fixed_hundred_hits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path, monkeypatch)
    resource = store.put_text("x" * 150)
    reader = _reader(store, search_limit=500)

    result = reader.search(resource.semantic_alias, "x")

    assert result["hit_count"] == 150
    assert len(result["hits"]) == 100
    assert result["truncated"] is True


def _old_json_search_hits(
    text: str,
    query: str,
    *,
    offset: int,
    limit: int,
) -> tuple[int, list[dict[str, object]]]:
    spans = _JsonSpanParser(text).parse()
    hits: list[dict[str, object]] = []
    logical_count = 0
    for start, end in _substring_matches(text, query):
        containing = [span for span in spans if span.start <= start and end <= span.end]
        if not containing:
            continue
        span = min(containing, key=lambda item: item.end - item.start)
        if offset <= logical_count < offset + limit:
            hits.append(
                {
                    "path": span.path,
                    "offset": start,
                    "tokens": FallbackTokenEstimator().count(
                        text[span.value_start : span.value_end]
                    ),
                }
            )
        logical_count += 1
    return logical_count, hits


@pytest.mark.parametrize(
    ("text", "queries"),
    [
        (
            '  {"a":"needle","b": ["nee","dle", {"needle":"needle"}]}  ',
            ("needle", "nee", '"needle"', "  "),
        ),
        ('{"outer":{"same":"same"},"same":"same"}', ("same", '"same":"same"', "outer")),
        ('["a","a","a",{"a":["a","a"]}]', ("a", '"a","a"', "missing")),
        (
            '{"x":"left\\"needle-right","needleKey":"v"}',
            ("needle", "needleKey", '"needleKey"'),
        ),
    ],
)
def test_json_search_ordered_sweep_matches_old_containment_oracle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    text: str,
    queries: tuple[str, ...],
) -> None:
    store = _store(tmp_path, monkeypatch)
    resource = store.put_bytes(text.encode("utf-8"))
    reader = _reader(store, search_limit=2)

    for query in queries:
        for offset in (0, 1, 3, 20):
            expected_count, expected_hits = _old_json_search_hits(
                text,
                query,
                offset=offset,
                limit=2,
            )
            result = reader.search(resource.semantic_alias, query, offset=offset)
            assert result["hit_count"] == expected_count
            assert result["hits"] == expected_hits
            assert result.get("truncated", False) == (offset + 2 < expected_count)


def test_json_search_sweeps_spans_once_and_enriches_only_requested_window(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import houbridge.resource.reader as reader_module

    text = "[" + ",".join('"needle"' for _ in range(400)) + "]"
    needle_offsets = [match.start() for match in re.finditer("needle", text)]
    store = _store(tmp_path, monkeypatch)
    resource = store.put_bytes(text.encode("utf-8"))
    visits = 0
    parsed_spans = 0
    original_parse = reader_module._JsonSpanParser.parse

    class _CountingSpans(list):
        def __iter__(self):
            nonlocal visits
            for span in super().__iter__():
                visits += 1
                yield span

    def counted_parse(parser):
        nonlocal parsed_spans
        spans = original_parse(parser)
        parsed_spans = len(spans)
        return _CountingSpans(spans)

    class _CountingEstimator:
        def __init__(self) -> None:
            self.calls = 0

        def count(self, text: str) -> int:
            self.calls += 1
            return FallbackTokenEstimator().count(text)

    monkeypatch.setattr(reader_module._JsonSpanParser, "parse", counted_parse)
    estimator = _CountingEstimator()
    reader = ResourceReader(
        store, inline_limit_bytes=16384, search_limit=2, token_estimator=estimator
    )

    result = reader.search(resource.semantic_alias, "needle", offset=398)

    assert result == {
        "hit_count": 400,
        "hits": [
            {
                "path": "$[398]",
                "offset": needle_offsets[398],
                "tokens": FallbackTokenEstimator().count('"needle"'),
            },
            {
                "path": "$[399]",
                "offset": text.rindex("needle"),
                "tokens": FallbackTokenEstimator().count('"needle"'),
            },
        ],
    }
    assert visits <= parsed_spans
    assert estimator.calls == 2
    assert result.get("truncated", False) is False
