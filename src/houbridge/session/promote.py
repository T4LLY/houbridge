from __future__ import annotations

from houbridge.errors import BridgeError

from .registry import SessionRegistry, SessionRegistryState
from .resolver import SessionResolver
from .stale import SessionStaleCleanupService


class SessionPromoteService:
    """Explicitly replace the registry primary with one validated live session."""

    def __init__(
        self,
        registry: SessionRegistry,
        resolver: SessionResolver,
        *,
        stale_cleanup: SessionStaleCleanupService | None = None,
    ) -> None:
        self._registry = registry
        self._resolver = resolver
        self._stale_cleanup = stale_cleanup or SessionStaleCleanupService(registry)

    def promote(self, session: int) -> dict[str, int]:
        _require_positive_session(session)
        with self._registry.locked():
            cleanup = self._stale_cleanup.cleanup_locked()
            record = cleanup.state.sessions.get(session)

        self._stale_cleanup.retire_best_effort(cleanup.stale_records)
        if record is None:
            raise BridgeError(
                "session_not_found",
                f"Registered Houdini session {session} does not exist.",
            )

        self._resolver.resolve_record(record)

        with self._registry.locked():
            current = self._registry.load()
            if current.sessions.get(session) != record:
                raise BridgeError(
                    "session_unreachable",
                    f"Registered Houdini session {session} changed during promotion.",
                )
            self._registry.save(
                SessionRegistryState(primary=session, sessions=current.sessions)
            )
        return {"primary": session}


def _require_positive_session(value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise BridgeError("invalid_session", "SESSION must be a positive integer.")
