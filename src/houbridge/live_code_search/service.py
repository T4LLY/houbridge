from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from houbridge.errors import BridgeError
from houbridge.formatting import SearchScoreMetric, format_search_score
from houbridge.resource.store import ResourceStore
from houbridge.session.resolver import SessionResolver

from .capture import LiveCodeCapture
from .models import LiveCodeEntry, RankedLiveCode


class LiveCodeRanker(Protocol):
    def hybrid(
        self,
        entries: Sequence[LiveCodeEntry],
        query: str,
        *,
        top_k: int,
    ) -> list[RankedLiveCode]: ...

    def dense(
        self,
        entries: Sequence[LiveCodeEntry],
        query_source: str,
        *,
        top_k: int,
    ) -> list[RankedLiveCode]: ...


class LiveCodeSearchService:
    """Capture current Houdini code, rank transiently, and Resource-back hits."""

    def __init__(
        self,
        resolver: SessionResolver,
        capture: LiveCodeCapture,
        ranker: LiveCodeRanker,
        resources: ResourceStore,
    ) -> None:
        self._resolver = resolver
        self._capture = capture
        self._ranker = ranker
        self._resources = resources

    def search(
        self,
        *,
        language: str,
        query: str | None,
        like: str | None,
        top_k: int = 10,
        path: str | None = None,
        recursive: bool = False,
        session: int | None = None,
    ) -> dict[str, object]:
        mode = _validate_request(language, query=query, like=like, top_k=top_k)
        resolved = self._resolver.resolve(session)
        captured = self._capture.capture(resolved, path=path, recursive=recursive)
        candidates = [entry for entry in captured if entry.language == language]

        if mode == "query":
            assert query is not None
            ranked = self._ranker.hybrid(candidates, query, top_k=top_k)
            return {"hits": self._present(ranked, dense=False)}

        assert like is not None
        source_entries = [
            entry for entry in captured if entry.language == language and entry.path == like
        ]
        if not source_entries:
            source_entries = [
                entry
                for entry in self._capture.capture(resolved, path=like, recursive=False)
                if entry.language == language and entry.path == like
            ]
        if not source_entries:
            raise BridgeError(
                "node_code_unavailable",
                f"No {language} code was found at Houdini node path: {like}",
            )
        query_source = "\n\n".join(
            entry.source for entry in sorted(source_entries, key=lambda item: item.slot_id)
        )
        dense_candidates = [entry for entry in candidates if entry.path != like]
        ranked = self._ranker.dense(dense_candidates, query_source, top_k=top_k)
        return {"hits": self._present(ranked, dense=True)}

    def _present(
        self,
        ranked: Sequence[RankedLiveCode],
        *,
        dense: bool,
    ) -> list[dict[str, object]]:
        metric = (
            SearchScoreMetric.DENSE_COSINE
            if dense
            else SearchScoreMetric.RECIPROCAL_RANK_FUSION
        )
        hits: list[dict[str, object]] = []
        for item in ranked:
            resource = self._resources.put_text(item.entry.source)
            hits.append(
                {
                    "path": item.entry.path,
                    "node_type": item.entry.node_type,
                    "resource": resource.semantic_alias,
                    "score": format_search_score(item.score, metric=metric),
                }
            )
        return hits


def _validate_request(
    language: str,
    *,
    query: str | None,
    like: str | None,
    top_k: int,
) -> str:
    if language not in {"python", "vex"}:
        raise ValueError("language must be python or vex")
    has_query = query is not None
    has_like = like is not None
    if has_query == has_like:
        raise BridgeError(
            "invalid_code_search_query",
            "Exactly one of QUERY or --like NODE_PATH must be supplied.",
        )
    if top_k < 1 or top_k > 50:
        raise BridgeError("invalid_top_k", "Live-code search --top-k must be between 1 and 50.")
    return "query" if has_query else "like"
