from __future__ import annotations

import socket
from dataclasses import dataclass
from typing import Callable, Iterable

from houbridge.process_coordination import ProcessIdentity, process_identity_for_pid

from .registry import SessionRecord, SessionRegistry, SessionRegistryState


PortStatusReader = Callable[[int], bool | None]


@dataclass(frozen=True, slots=True)
class StaleCleanupResult:
    state: SessionRegistryState
    stale_records: tuple[SessionRecord, ...]


class SessionStaleCleanupService:
    """Remove registry entries proven stale by process identity or closed port."""

    def __init__(
        self,
        registry: SessionRegistry,
        *,
        identity_reader: Callable[[int], ProcessIdentity] = process_identity_for_pid,
        port_status_reader: PortStatusReader | None = None,
        on_stale: Callable[[SessionRecord], None] | None = None,
    ) -> None:
        self._registry = registry
        self._identity_reader = identity_reader
        self._port_status_reader = (
            _local_port_status if port_status_reader is None else port_status_reader
        )
        self._on_stale = on_stale

    def cleanup(self) -> SessionRegistryState:
        with self._registry.locked():
            result = self.cleanup_locked()
        self.retire_best_effort(result.stale_records)
        return result.state

    def cleanup_locked(self) -> StaleCleanupResult:
        """Commit stale registry removal while the caller holds the mutation lock."""

        state = self._registry.load()
        live: dict[int, SessionRecord] = {}
        stale_records: list[SessionRecord] = []
        for number, record in state.sessions.items():
            if self._record_is_live(record):
                live[number] = record
            else:
                stale_records.append(record)

        primary = state.primary if state.primary in live else None
        cleaned = SessionRegistryState(primary=primary, sessions=live)
        if primary != state.primary or len(live) != len(state.sessions):
            self._registry.save(cleaned)
        return StaleCleanupResult(
            state=cleaned,
            stale_records=tuple(stale_records),
        )

    def retire_best_effort(self, records: Iterable[SessionRecord]) -> None:
        """Run optional stale side effects only after registry state is committed."""

        if self._on_stale is None:
            return
        for record in records:
            try:
                self._on_stale(record)
            except OSError:
                # History retirement is optional cleanup. Files can remain locked
                # temporarily on Windows without making Session state invalid.
                continue

    def _record_is_live(self, record: SessionRecord) -> bool:
        try:
            identity = self._identity_reader(record.pid)
        except ProcessLookupError:
            return False
        except OSError:
            # Cleanup is destructive. An identity read failure does not prove
            # that the recorded process is dead, so preserve the registration.
            return True

        if identity.pid != record.pid:
            return False
        if (
            record.process_start_identity is not None
            and identity.process_start_identity != record.process_start_identity
        ):
            return False

        # Cleanup is destructive. Only an explicit connection refusal proves that
        # the registered local listener is gone; timeout and other socket errors
        # can occur while Houdini is busy or the host is temporarily constrained.
        return self._port_status_reader(record.port) is not False


def _local_port_status(port: int) -> bool | None:
    """Return True for open, False for refused, and None when inconclusive."""

    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.1):
            return True
    except ConnectionRefusedError:
        return False
    except OSError:
        return None
