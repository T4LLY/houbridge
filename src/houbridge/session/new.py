from __future__ import annotations

from pathlib import Path
from typing import Callable

from houbridge.process_coordination import ProcessIdentity, process_identity_for_pid

from .launcher import HoudiniSessionLauncher
from .registry import SessionRecord, SessionRegistry, SessionRegistryState
from .stale import SessionStaleCleanupService


class SessionNewService:
    """Register one newly launched process without probing for reusable targets."""

    def __init__(
        self,
        registry: SessionRegistry,
        launcher: HoudiniSessionLauncher,
        *,
        identity_reader: Callable[[int], ProcessIdentity] = process_identity_for_pid,
        on_stale: Callable[[SessionRecord], None] | None = None,
    ) -> None:
        self._registry = registry
        self._launcher = launcher
        self._stale_cleanup = SessionStaleCleanupService(
            registry,
            identity_reader=identity_reader,
            on_stale=on_stale,
        )

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
            with self._registry.locked():
                registry_existed = self._registry.path.exists()
                state = self._stale_cleanup.cleanup_locked()
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
                self._registry.save(
                    SessionRegistryState(primary=primary, sessions=sessions)
                )
        except BaseException:
            self._launcher.terminate(launch)
            raise

        return {"session": number, "port": launch.port, "pid": launch.pid}


def _smallest_unused_session(state: SessionRegistryState) -> int:
    number = 1
    while number in state.sessions:
        number += 1
    return number
