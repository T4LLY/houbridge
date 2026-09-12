from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class LiveCodeEntry:
    session_id: int
    path: str
    node_type: str
    slot_id: str
    parameter_name: str
    language: str
    source: str

    @property
    def entry_id(self) -> str:
        return f"{self.session_id}:{self.slot_id}"


@dataclass(frozen=True, slots=True)
class RankedLiveCode:
    entry: LiveCodeEntry
    score: float
