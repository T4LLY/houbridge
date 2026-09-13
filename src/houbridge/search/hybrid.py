from __future__ import annotations

from collections.abc import Callable, Sequence

from houbridge.search.rrf import reciprocal_rank_fusion


Ranker = Callable[[int], Sequence[str]]


def hybrid_rank(
    *,
    total_count: int,
    top_k: int,
    candidate_min: int,
    candidate_multiplier: int,
    rrf_k: int,
    dense_rank: Ranker,
    lexical_rank: Ranker,
) -> dict[str, float]:
    """Fuse dense and lexical rankings using one shared candidate policy."""

    if total_count <= 0 or top_k <= 0:
        return {}

    candidate_limit = min(
        total_count,
        max(candidate_min, top_k * candidate_multiplier),
    )
    return reciprocal_rank_fusion(
        [
            list(dense_rank(candidate_limit)),
            list(lexical_rank(candidate_limit)),
        ],
        k=rrf_k,
    )
