from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class LiveNodeEntry:
    path: str
    name: str
    type: str
    category: str
