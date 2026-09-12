from __future__ import annotations

from pathlib import Path
from typing import Callable

from houbridge.errors import BridgeError
from houbridge.process_coordination import ProcessIdentity, process_identity_for_pid

from .launcher import HoudiniSessionLauncher, SessionLaunchResult
from .registry import SessionRecord, SessionRegistry, SessionRegistryState


class SessionNewService:
    """Register one newly launched process without probing for reusable targets."""

    def __init__(
        self,
        registry: SessionRegistry,
        launcher: HoudiniSessionLauncher,
        *,
        identity_reader: Callable[[int], ProcessIdentity] = process_identity_for_pid,
    ) -> None:
        self._registry = registry
        self._launcher = launcher
        self._identity_reader = identity_reader

    def create(
        self,
        *,
        hip_file: Path | None = None,
        headless: bool = False,
        hcommand: Path | None = None,
    ) -> dict[str, object]:
        launch = self._launcher.launch(
            hip_file=hip_file,
            headless=headless,
            hcommand=hcommand,
        )
        try:
            registry_existed = self._registry.path.exists()
            state = self._registry.load()
            state = self._without_stale_records(state)
            number = _smallest_unused_session(state)
            sessions = dict(state.sessions)
            sessions[number] = SessionRecord(
                session=number,
                port=launch.port,
                pid=launch.pid,
                process_start_identity=launch.identity.process_start_identity,
            )
            primary = state.primary
            if not registry_existed:
                primary = number
            self._registry.save(SessionRegistryState(primary=primary, sessions=sessions))
        except BaseException:
            self._launcher.terminate(launch)
            raise

        return {"session": number, "port": launch.port, "pid": launch.pid}

    def _without_stale_records(self, state: SessionRegistryState) -> SessionRegistryState:
        live: dict[int, SessionRecord] = {}
        for number, record in state.sessions.items():
            if self._record_is_live(record):
                live[number] = record
        primary = state.primary if state.primary in live else None
        return SessionRegistryState(primary=primary, sessions=live)

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


def _smallest_unused_session(state: SessionRegistryState) -> int:
    number = 1
    while number in state.sessions:
        number += 1
    return number
