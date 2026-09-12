from __future__ import annotations

from typing import Callable

from houbridge.process_coordination import ProcessIdentity, process_identity_for_pid

from .registry import SessionRecord, SessionRegistry, SessionRegistryState


class SessionStaleCleanupService:
    """Remove registry entries proven stale by operating-system process identity."""

    def __init__(
        self,
        registry: SessionRegistry,
        *,
        identity_reader: Callable[[int], ProcessIdentity] = process_identity_for_pid,
    ) -> None:
        self._registry = registry
        self._identity_reader = identity_reader

    def cleanup(self) -> SessionRegistryState:
        state = self._registry.load()
        live: dict[int, SessionRecord] = {}
        for number, record in state.sessions.items():
            if self._record_is_live(record):
                live[number] = record

        primary = state.primary if state.primary in live else None
        cleaned = SessionRegistryState(primary=primary, sessions=live)
        if primary != state.primary or len(live) != len(state.sessions):
            self._registry.save(cleaned)
        return cleaned

    def _record_is_live(self, record: SessionRecord) -> bool:
        try:
            identity = self._identity_reader(record.pid)
        except (ProcessLookupError, PermissionError, OSError):
            return False

        if identity.pid != record.pid:
            return False
        if (
            record.process_start_identity is not None
            and identity.process_start_identity != record.process_start_identity
        ):
            return False
        return True
