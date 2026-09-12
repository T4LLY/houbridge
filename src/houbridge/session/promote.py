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
        state = self._stale_cleanup.cleanup()
        record = state.sessions.get(session)
        if record is None:
            raise BridgeError(
                "session_not_found",
                f"Registered Houdini session {session} does not exist.",
            )

        self._resolver.resolve_record(record)
        self._registry.save(
            SessionRegistryState(primary=session, sessions=state.sessions)
        )
        return {"primary": session}


def _require_positive_session(value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise BridgeError("invalid_session", "SESSION must be a positive integer.")
