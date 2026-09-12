from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


ContentClass = Literal["binary", "text", "json"]


@dataclass(frozen=True, slots=True)
class Resource:
    canonical_id: str
    semantic_alias: str
    content_class: ContentClass
    mime: str
    byte_size: int
    token_count: int | None
    created_at: str
    expires_at: str
