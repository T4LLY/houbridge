from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
import math
import re
from typing import SupportsFloat


_JSON_NUMBER = re.compile(r"-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?\Z")


@dataclass(frozen=True)
class CanonicalJsonNumber:
    """A validated JSON number token whose lexical form must be preserved."""

    token: str

    def __post_init__(self) -> None:
        if not _JSON_NUMBER.fullmatch(self.token):
            raise ValueError(f"invalid JSON number token: {self.token!r}")


class SearchScoreMetric(str, Enum):
    DENSE_COSINE = "dense_cosine"
    RECIPROCAL_RANK_FUSION = "reciprocal_rank_fusion"


_SEARCH_SCORE_SCALE = {
    SearchScoreMetric.DENSE_COSINE: Decimal("1000"),
    SearchScoreMetric.RECIPROCAL_RANK_FUSION: Decimal("10000"),
}


def format_public_datetime(value: datetime) -> str:
    """Format a public date-time without changing the feature-owned time basis."""

    return value.strftime("%Y-%m-%dT%H:%M:%S")


def format_search_score(
    raw_score: Decimal | SupportsFloat | str,
    *,
    metric: SearchScoreMetric,
) -> CanonicalJsonNumber:
    """Scale and normalize a public Search score to exactly six decimals."""

    if isinstance(raw_score, Decimal):
        score = raw_score
    elif isinstance(raw_score, str):
        score = Decimal(raw_score)
    else:
        numeric = float(raw_score)
        if not math.isfinite(numeric):
            raise ValueError("Search score must be finite.")
        score = Decimal(str(numeric))

    scaled = score * _SEARCH_SCORE_SCALE[metric]
    return CanonicalJsonNumber(format(scaled, ".6f"))
