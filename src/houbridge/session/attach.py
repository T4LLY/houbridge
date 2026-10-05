from __future__ import annotations

from typing import Callable

from houbridge.errors import BridgeError
from houbridge.process_coordination import ProcessIdentity, process_identity_for_pid

from .probe import SessionProbe, SessionProbeResult
from .registry import SessionRecord, SessionRegistry, SessionRegistryState
from .stale import PortStatusReader, SessionStaleCleanupService


class SessionAttachService:
    """Register an already-running Houdini process through a manually opened port."""

    def __init__(
        self,
        registry: SessionRegistry,
        probe: SessionProbe,
        *,
        identity_reader: Callable[[int], ProcessIdentity] = process_identity_for_pid,
        port_status_reader: PortStatusReader | None = None,
        on_stale: Callable[[SessionRecord], None] | None = None,
    ) -> None:
        self._registry = registry
        self._probe = probe
        self._identity_reader = identity_reader
        self._stale_cleanup = SessionStaleCleanupService(
            registry,
            identity_reader=identity_reader,
            port_status_reader=port_status_reader,
            on_stale=on_stale,
        )

    def attach(self, port: int) -> dict[str, int]:
        _require_port(port)
        probe, identity = self._validate_target(port)

        with self._registry.locked():
            registry_existed = self._registry.path.exists()
            cleanup = self._stale_cleanup.cleanup_locked()
            state = cleanup.state

            current_identity = self._read_identity(probe.pid)
            if current_identity != identity:
                raise BridgeError(
                    "session_attach_unreachable",
                    "The operating-system process incarnation changed before registration.",
                    f"pid={probe.pid}",
                )

            existing = _find_registered_process(state, probe.pid, identity)
            conflict: BridgeError | None = None
            if existing is not None:
                if existing.port != port:
                    conflict = BridgeError(
                        "session_already_registered",
                        f"Houdini PID {probe.pid} is already registered as session {existing.session}.",
                        f"registered_port={existing.port}; requested_port={port}",
                    )
                payload = {
                    "session": existing.session,
                    "port": existing.port,
                    "pid": existing.pid,
                }
            else:
                number = _smallest_unused_session(state)
                sessions = dict(state.sessions)
                sessions[number] = SessionRecord(
                    session=number,
                    port=port,
                    pid=probe.pid,
                    process_start_identity=identity.process_start_identity,
                )
                primary = state.primary
                if not registry_existed or not state.sessions:
                    primary = number
                self._registry.save(
                    SessionRegistryState(primary=primary, sessions=sessions)
                )
                payload = {"session": number, "port": port, "pid": probe.pid}

        self._stale_cleanup.retire_best_effort(cleanup.stale_records)
        if conflict is not None:
            raise conflict
        return payload

    def _validate_target(self, port: int) -> tuple[SessionProbeResult, ProcessIdentity]:
        initial = self._probe.inspect(port)
        if port not in initial.open_ports:
            raise BridgeError(
                "session_attach_unreachable",
                "The selected Houdini process does not report the requested openport.",
                f"port={port}; pid={initial.pid}",
            )

        before = self._read_identity(initial.pid)
        confirmed = self._probe.inspect(port)
        if confirmed.pid != initial.pid:
            raise BridgeError(
                "session_attach_unreachable",
                "The Houdini process behind the requested port changed during attach.",
                f"initial_pid={initial.pid}; confirmed_pid={confirmed.pid}",
            )
        if port not in confirmed.open_ports:
            raise BridgeError(
                "session_attach_unreachable",
                "The requested openport disappeared during attach.",
                f"port={port}; pid={confirmed.pid}",
            )

        after = self._read_identity(confirmed.pid)
        if after != before:
            raise BridgeError(
                "session_attach_unreachable",
                "The operating-system process incarnation changed during attach.",
                f"pid={confirmed.pid}",
            )
        return confirmed, after

    def _read_identity(self, pid: int) -> ProcessIdentity:
        try:
            identity = self._identity_reader(pid)
        except (ProcessLookupError, PermissionError, OSError) as exc:
            raise BridgeError(
                "session_attach_unreachable",
                "The Houdini process behind the requested port is not reachable.",
                f"pid={pid}; {type(exc).__name__}: {exc}",
            ) from exc
        if identity.pid != pid:
            raise BridgeError(
                "session_attach_unreachable",
                "Process identity lookup returned a different PID during attach.",
                f"expected_pid={pid}; actual_pid={identity.pid}",
            )
        return identity


def _find_registered_process(
    state: SessionRegistryState,
    pid: int,
    identity: ProcessIdentity,
) -> SessionRecord | None:
    for record in state.sessions.values():
        if record.pid != pid:
            continue
        if (
            record.process_start_identity is not None
            and record.process_start_identity != identity.process_start_identity
        ):
            continue
        return record
    return None


def _smallest_unused_session(state: SessionRegistryState) -> int:
    number = 1
    while number in state.sessions:
        number += 1
    return number


def _require_port(value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 65535:
        raise BridgeError("invalid_port", "PORT must be an integer in the range 1..65535.")
