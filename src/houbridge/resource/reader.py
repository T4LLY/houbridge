from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from json.decoder import scanstring
from typing import Any

from houbridge.config import HARD_EMIT_LIMIT_BYTES, HARD_RESOURCE_SEARCH_LIMIT
from houbridge.errors import BridgeError
from houbridge.output.json import public_json_size
from houbridge.output.tokens import FallbackTokenEstimator, TokenEstimator
from houbridge.resource.models import Resource
from houbridge.resource.store import ResourceStore


HARD_RESOURCE_SLICE_LIMIT_BYTES = 16384
_JSON_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass(frozen=True, slots=True)
class _JsonMatchSpan:
    start: int
    end: int
    path: str
    value_start: int
    value_end: int


class _JsonSpanParser:
    """Map source spans to their narrowest containing JSON value."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.length = len(text)
        self.spans: list[_JsonMatchSpan] = []
        self.decoder = json.JSONDecoder(
            parse_constant=_reject_non_finite_json_constant,
        )

    def parse(self) -> list[_JsonMatchSpan]:
        try:
            start = self._skip_ws(0)
            end = self._parse_value(start, "$")
            if self._skip_ws(end) != self.length:
                raise self._invalid_json()
            return self.spans
        except RecursionError as exc:
            raise self._invalid_json() from exc

    def _parse_value(self, start: int, path: str) -> int:
        start = self._skip_ws(start)
        if start >= self.length:
            raise self._invalid_json()

        char = self.text[start]
        if char == "{":
            end = self._parse_object(start, path)
        elif char == "[":
            end = self._parse_array(start, path)
        else:
            try:
                _value, end = self.decoder.raw_decode(self.text, start)
            except (json.JSONDecodeError, ValueError) as exc:
                raise self._invalid_json() from exc

        self.spans.append(_JsonMatchSpan(start, end, path, start, end))
        return end

    def _parse_object(self, start: int, path: str) -> int:
        index = self._skip_ws(start + 1)
        if index < self.length and self.text[index] == "}":
            return index + 1

        while True:
            index = self._skip_ws(index)
            if index >= self.length or self.text[index] != '"':
                raise self._invalid_json()
            key_start = index
            try:
                key, key_end = scanstring(self.text, index + 1, True)
            except (ValueError, json.JSONDecodeError) as exc:
                raise self._invalid_json() from exc

            index = self._skip_ws(key_end)
            if index >= self.length or self.text[index] != ":":
                raise self._invalid_json()

            child_path = _json_child_path(path, key)
            value_start = self._skip_ws(index + 1)
            value_end = self._parse_value(value_start, child_path)
            # A key match belongs to the value addressed by that key.
            self.spans.append(
                _JsonMatchSpan(
                    key_start,
                    key_end,
                    child_path,
                    value_start,
                    value_end,
                )
            )

            index = self._skip_ws(value_end)
            if index >= self.length:
                raise self._invalid_json()
            if self.text[index] == "}":
                return index + 1
            if self.text[index] != ",":
                raise self._invalid_json()
            index += 1

    def _parse_array(self, start: int, path: str) -> int:
        index = self._skip_ws(start + 1)
        if index < self.length and self.text[index] == "]":
            return index + 1

        item_index = 0
        while True:
            child_path = f"{path}[{item_index}]"
            index = self._parse_value(index, child_path)
            index = self._skip_ws(index)
            if index >= self.length:
                raise self._invalid_json()
            if self.text[index] == "]":
                return index + 1
            if self.text[index] != ",":
                raise self._invalid_json()
            index = self._skip_ws(index + 1)
            item_index += 1

    def _skip_ws(self, index: int) -> int:
        while index < self.length and self.text[index] in " \t\r\n":
            index += 1
        return index

    @staticmethod
    def _invalid_json() -> BridgeError:
        return BridgeError("invalid_json_resource", "Resource contains invalid JSON.")


def _reject_non_finite_json_constant(_value: str) -> None:
    raise ValueError("Non-finite numbers are not valid JSON.")


def _json_child_path(parent: str, key: str) -> str:
    if _JSON_IDENTIFIER.fullmatch(key):
        return f"{parent}.{key}"
    encoded = json.dumps(key, ensure_ascii=False)
    return f"{parent}[{encoded}]"


def _substring_matches(text: str, query: str) -> list[tuple[int, int]]:
    pattern = re.compile(re.escape(query), re.IGNORECASE)
    return [(match.start(), match.end()) for match in pattern.finditer(text)]


def _utf8_prefix(text: str, max_bytes: int) -> str:
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    return encoded[:max_bytes].decode("utf-8", errors="ignore")


def _parse_json_resource(text: str) -> Any:
    try:
        return json.loads(text, parse_constant=_reject_non_finite_json_constant)
    except (json.JSONDecodeError, ValueError, RecursionError) as exc:
        raise BridgeError(
            "invalid_json_resource",
            "Resource contains invalid JSON.",
        ) from exc


@dataclass(frozen=True, slots=True)
class ResourceReader:
    store: ResourceStore
    inline_limit_bytes: int
    search_limit: int
    token_estimator: TokenEstimator = field(default_factory=FallbackTokenEstimator)

    def __post_init__(self) -> None:
        if self.inline_limit_bytes < 1:
            raise ValueError("inline_limit_bytes must be >= 1")
        if self.search_limit < 1:
            raise ValueError("search_limit must be >= 1")
        object.__setattr__(
            self,
            "search_limit",
            min(self.search_limit, HARD_RESOURCE_SEARCH_LIMIT),
        )

    def info(self, resource_id: str) -> dict[str, object]:
        resource = self._require_resource(resource_id)
        if resource.content_class == "binary":
            return {"mime": resource.mime, "bytes": resource.byte_size}
        if resource.token_count is None:
            raise BridgeError(
                "resource_metadata_invalid",
                "Text Resource is missing its token count.",
            )
        return {"mime": resource.mime, "tokens": resource.token_count}

    def get(self, resource_id: str, *, full: bool = False) -> dict[str, object]:
        self._validate_resource_id(resource_id)
        snapshot = self.store.get_payload(resource_id)
        if snapshot is None:
            self._raise_not_found(resource_id)
        resource, payload = snapshot

        if resource.content_class == "binary":
            return {"truncated": False, "binary": True}

        if resource.byte_size > self.inline_limit_bytes and not full:
            return {"truncated": True, "next_offset": 0}

        text = self._decode_text(payload)
        result: object = (
            _parse_json_resource(text)
            if resource.content_class == "json"
            else text
        )
        response: dict[str, object] = {"truncated": False, "result": result}
        if public_json_size(response) > HARD_EMIT_LIMIT_BYTES:
            return {"truncated": True, "next_offset": 0}
        return response

    def slice(self, resource_id: str, *, offset: int, limit: int) -> dict[str, object]:
        if offset < 0:
            raise BridgeError("invalid_slice", "offset must be >= 0.")
        if limit < 1:
            raise BridgeError("invalid_slice", "limit must be >= 1.")
        if limit > HARD_RESOURCE_SLICE_LIMIT_BYTES:
            raise BridgeError(
                "resource_slice_limit_exceeded",
                (
                    "Resource slice limit exceeds the fixed hard limit of "
                    f"{HARD_RESOURCE_SLICE_LIMIT_BYTES} UTF-8 bytes."
                ),
            )

        _resource, text = self._require_text_payload(resource_id)
        requested = text[offset : offset + limit]
        chunk = _utf8_prefix(requested, HARD_RESOURCE_SLICE_LIMIT_BYTES)
        next_offset = offset + len(chunk)
        response: dict[str, object] = {"result": chunk}
        if next_offset < len(text):
            response["truncated"] = True
            response["next_offset"] = next_offset
        return response

    def search(
        self,
        resource_id: str,
        query: str,
        *,
        offset: int = 0,
    ) -> dict[str, object]:
        if not query:
            raise BridgeError("empty_query", "Resource search query must not be empty.")
        if offset < 0:
            raise BridgeError("invalid_search_offset", "offset must be >= 0.")

        resource, text = self._require_text_payload(resource_id)
        matches = _substring_matches(text, query)
        if resource.content_class == "json":
            all_hits = self._json_hits(text, matches)
        else:
            all_hits = [{"offset": start} for start, _end in matches]

        end = offset + self.search_limit
        response: dict[str, object] = {
            "hit_count": len(all_hits),
            "hits": all_hits[offset:end],
        }
        if end < len(all_hits):
            response["truncated"] = True
        return response

    def _json_hits(
        self,
        text: str,
        matches: list[tuple[int, int]],
    ) -> list[dict[str, object]]:
        spans = _JsonSpanParser(text).parse()
        hits: list[dict[str, object]] = []
        token_cache: dict[tuple[int, int], int] = {}

        for start, end in matches:
            containing = [
                span
                for span in spans
                if span.start <= start and end <= span.end
            ]
            if not containing:
                continue
            span = min(containing, key=lambda item: item.end - item.start)
            token_span = (span.value_start, span.value_end)
            if token_span not in token_cache:
                token_cache[token_span] = self.token_estimator.count(
                    text[span.value_start : span.value_end]
                )
            hits.append(
                {
                    "path": span.path,
                    "offset": start,
                    "tokens": token_cache[token_span],
                }
            )
        return hits

    def _require_resource(self, resource_id: str) -> Resource:
        self._validate_resource_id(resource_id)
        resource = self.store.get(resource_id)
        if resource is None:
            self._raise_not_found(resource_id)
        return resource

    def _require_text_payload(self, resource_id: str) -> tuple[Resource, str]:
        self._validate_resource_id(resource_id)
        snapshot = self.store.get_payload(resource_id)
        if snapshot is None:
            self._raise_not_found(resource_id)
        resource, payload = snapshot
        if resource.content_class == "binary":
            raise BridgeError(
                "resource_not_text",
                "This operation is available only for text and JSON Resources.",
            )
        return resource, self._decode_text(payload)

    @staticmethod
    def _decode_text(payload: bytes) -> str:
        try:
            return payload.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise BridgeError(
                "resource_text_invalid",
                "Resource text payload is not valid UTF-8.",
            ) from exc

    @staticmethod
    def _validate_resource_id(resource_id: str) -> None:
        if not isinstance(resource_id, str) or not resource_id:
            raise BridgeError("invalid_resource_id", "Resource id must not be empty.")

    @staticmethod
    def _raise_not_found(resource_id: str) -> None:
        raise BridgeError("resource_not_found", f"Resource not found: {resource_id}")
