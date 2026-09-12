from __future__ import annotations

from collections.abc import Sequence


def reciprocal_rank_fusion(
    rankings: Sequence[Sequence[str]],
    *,
    k: int,
    weights: Sequence[float] | None = None,
) -> dict[str, float]:
    """Fuse rank positions only; public score formatting stays in formatting.py."""

    if k < 0:
        raise ValueError("k must be >= 0")
    effective_weights = list(weights) if weights is not None else [1.0] * len(rankings)
    if len(effective_weights) != len(rankings):
        raise ValueError("weights must match rankings")

    scores: dict[str, float] = {}
    for ranking, weight in zip(rankings, effective_weights, strict=True):
        for rank, entry_id in enumerate(ranking, start=1):
            scores[entry_id] = scores.get(entry_id, 0.0) + weight / (k + rank)
    return scores
