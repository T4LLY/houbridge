from __future__ import annotations

import math
from typing import Protocol


class TokenEstimator(Protocol):
    """Shared token-estimation boundary used by Output and Resource."""

    def count(self, text: str) -> int:
        ...


class FallbackTokenEstimator:
    """Dependency-free token estimate used until a model-specific estimator is supplied."""

    def count(self, text: str) -> int:
        if not text:
            return 0
        return max(1, math.ceil(len(text.encode("utf-8")) / 3))
