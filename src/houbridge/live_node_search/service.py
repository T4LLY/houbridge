from __future__ import annotations

from collections.abc import Sequence

from houbridge.errors import BridgeError
from houbridge.session.resolver import SessionResolver

from .capture import LiveNodeCapture
from .models import LiveNodeEntry


class LiveNodeSearchService:
    """Search current node instances with deterministic non-semantic ranking."""

    def __init__(self, resolver: SessionResolver, capture: LiveNodeCapture) -> None:
        self._resolver = resolver
        self._capture = capture

    def search(
        self,
        query: str,
        *,
        top_k: int = 20,
        path: str | None = None,
        recursive: bool = False,
        session: int | None = None,
    ) -> dict[str, object]:
        needle = query.strip().casefold()
        if not needle:
            raise BridgeError("empty_query", "Node search query must not be empty.")
        if top_k < 1 or top_k > 100:
            raise BridgeError("invalid_top_k", "Live node search --top-k must be between 1 and 100.")

        resolved = self._resolver.resolve(session)
        entries = self._capture.capture(resolved, path=path, recursive=recursive)
        ranked = _rank(entries, needle)[:top_k]
        return {
            "hits": [
                {
                    "path": entry.path,
                    "name": entry.name,
                    "type": entry.type,
                    "category": entry.category,
                }
                for entry in ranked
            ]
        }


def _rank(entries: Sequence[LiveNodeEntry], needle: str) -> list[LiveNodeEntry]:
    matches: list[tuple[int, str, str, LiveNodeEntry]] = []
    for entry in entries:
        rank = _match_class(entry, needle)
        if rank is None:
            continue
        matches.append((rank, entry.path.casefold(), entry.path, entry))
    matches.sort(key=lambda item: item[:3])
    return [item[3] for item in matches]


def _match_class(entry: LiveNodeEntry, needle: str) -> int | None:
    fields = (entry.name.casefold(), entry.type.casefold(), entry.category.casefold())
    if needle in fields:
        return 0
    if any(field.startswith(needle) for field in fields):
        return 1
    if any(needle in field for field in fields):
        return 2
    return None
