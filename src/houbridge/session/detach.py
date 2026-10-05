from __future__ import annotations

from houbridge.errors import BridgeError

from .registry import SessionRegistry, SessionRegistryState


class SessionDetachService:
    """Remove one Session registration without touching the Houdini process."""

    def __init__(self, registry: SessionRegistry) -> None:
        self._registry = registry

    def detach(self, session: int) -> dict[str, int]:
        _require_positive_session(session)
        with self._registry.locked():
            state = self._registry.load()
            if session not in state.sessions:
                raise BridgeError(
                    "session_not_found",
                    f"Registered Houdini session {session} does not exist.",
                )

            sessions = dict(state.sessions)
            del sessions[session]
            primary = None if state.primary == session else state.primary
            self._registry.save(SessionRegistryState(primary=primary, sessions=sessions))

        return {"detached": session}


def _require_positive_session(value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise BridgeError("invalid_session", "SESSION must be a positive integer.")
