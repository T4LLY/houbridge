from __future__ import annotations

from houbridge.errors import BridgeError

from .registry import SessionRegistry
from .resolver import ResolvedSession, SessionResolver


class SessionInfoService:
    """Expose exactly the OpenSpec Session info public contract."""

    def __init__(self, registry: SessionRegistry, resolver: SessionResolver) -> None:
        self._registry = registry
        self._resolver = resolver

    def inspect(self, session: int | None = None) -> dict[str, object]:
        if session is not None:
            if isinstance(session, bool) or not isinstance(session, int) or session <= 0:
                raise BridgeError("invalid_session", "--session must be a positive integer.")
            state = self._registry.load()
            record = state.sessions.get(session)
            if record is None:
                raise BridgeError(
                    "session_not_found",
                    f"Registered Houdini session {session} does not exist.",
                )
            resolved = self._resolver.resolve_record(record)
            payload = _public_info(resolved)
            return {
                "session": session,
                "primary": state.primary == session,
                **payload,
            }

        state = self._registry.load()
        sessions: list[dict[str, object]] = []
        for number in sorted(state.sessions):
            resolved = self._resolver.resolve_record(state.sessions[number])
            sessions.append({"session": number, **_public_info(resolved)})
        return {"primary": state.primary, "sessions": sessions}


def _public_info(resolved: ResolvedSession) -> dict[str, object]:
    return {
        "port": resolved.record.port,
        "pid": resolved.probe.pid,
        "version": resolved.probe.version,
        "license": resolved.probe.license,
        "file": resolved.probe.file,
        "headless": resolved.probe.headless,
    }
