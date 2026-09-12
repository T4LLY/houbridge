from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from houbridge.errors import BridgeError
from houbridge.houdini.transport import HoudiniTarget
from houbridge.process_coordination import ProcessIdentity, process_identity_for_pid

from .probe import SessionProbe, SessionProbeResult
from .registry import SessionRecord, SessionRegistry


@dataclass(frozen=True, slots=True)
class ResolvedSession:
    record: SessionRecord
    identity: ProcessIdentity
    probe: SessionProbeResult

    @property
    def target(self) -> HoudiniTarget:
        return HoudiniTarget(host="127.0.0.1", port=self.record.port)


class SessionResolver:
    """Select and validate registered Houdini processes without fallback."""

    def __init__(
        self,
        registry: SessionRegistry,
        probe: SessionProbe,
        *,
        identity_reader: Callable[[int], ProcessIdentity] = process_identity_for_pid,
    ) -> None:
        self._registry = registry
        self._probe = probe
        self._identity_reader = identity_reader

    def resolve(self, session: int | None = None) -> ResolvedSession:
        state = self._registry.load()
        if session is None:
            if state.primary is None:
                raise BridgeError(
                    "session_primary_missing",
                    "No primary Houdini session is selected.",
                )
            session = state.primary
        _require_positive_session(session)
        record = state.sessions.get(session)
        if record is None:
            raise BridgeError(
                "session_not_found",
                f"Registered Houdini session {session} does not exist.",
            )
        return self.resolve_record(record)

    def resolve_record(self, record: SessionRecord) -> ResolvedSession:
        before = self._read_identity(record)
        probe = self._probe.inspect(record.port)
        if probe.pid != record.pid:
            raise _stale(record, "the registered port belongs to a different Houdini PID")
        if record.port not in probe.open_ports:
            raise _stale(record, "the registered openport is not reported by that Houdini process")
        after = self._read_identity(record)
        if after != before:
            raise _stale(record, "the operating-system process incarnation changed during validation")
        return ResolvedSession(record=record, identity=after, probe=probe)

    def _read_identity(self, record: SessionRecord) -> ProcessIdentity:
        try:
            identity = self._identity_reader(record.pid)
        except (ProcessLookupError, PermissionError, OSError) as exc:
            raise _stale(record, "the registered PID is not a reachable live process") from exc
        if identity.pid != record.pid:
            raise _stale(record, "process identity reader returned a different PID")
        if (
            record.process_start_identity is not None
            and identity.process_start_identity != record.process_start_identity
        ):
            raise _stale(record, "the registered PID has been reused by another process")
        return identity


def _require_positive_session(value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise BridgeError("invalid_session", "--session must be a positive integer.")


def _stale(record: SessionRecord, reason: str) -> BridgeError:
    return BridgeError(
        "session_unreachable",
        f"Registered Houdini session {record.session} is unavailable.",
        reason,
    )
