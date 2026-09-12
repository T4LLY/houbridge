from __future__ import annotations

import os
import secrets
from typing import Callable, Protocol

from houbridge.process_coordination import ProcessIdentity, process_identity_for_pid

from .runtime_store import RuntimeOwner, TaskRuntimeStateStore


class RuntimeLauncher(Protocol):
    def __call__(self, owner_token: str) -> None:
        ...


class TaskRuntimeSupervisor:
    """Recover/activate on-demand runtime ownership without a permanent daemon."""

    def __init__(
        self,
        runtime_state: TaskRuntimeStateStore,
        *,
        identity_reader: Callable[[int], ProcessIdentity] = process_identity_for_pid,
        current_identity_reader: Callable[[], ProcessIdentity] | None = None,
        token_factory: Callable[[], str] | None = None,
    ) -> None:
        self._runtime_state = runtime_state
        self._identity_reader = identity_reader
        self._current_identity_reader = current_identity_reader or (
            lambda: process_identity_for_pid(os.getpid())
        )
        self._token_factory = token_factory or (lambda: secrets.token_hex(16))

    def ensure_active(self, launcher: RuntimeLauncher) -> bool:
        """Ensure recoverable work has one live owner/start handoff.

        Returns ``True`` only when this call reserved ownership and invoked the
        launcher. A live runtime (or a live process still performing the startup
        handoff) is left untouched.
        """

        while True:
            owner = self._runtime_state.runtime_owner()
            if owner is not None:
                if self._owner_is_live(owner):
                    return False
                self._runtime_state.clear_runtime_owner(owner.token)
                continue

            if not self._runtime_state.recoverable_work_exists():
                return False

            token = self._token_factory().strip()
            if not token:
                raise ValueError("runtime token factory returned an empty token")
            starter_identity = self._current_identity_reader()
            if not self._runtime_state.reserve_runtime_start(token, starter_identity):
                continue
            try:
                launcher(token)
            except BaseException:
                self._runtime_state.clear_runtime_owner(token)
                raise
            return True

    def _owner_is_live(self, owner: RuntimeOwner) -> bool:
        expected = owner.runtime_identity or owner.starter_identity
        try:
            current = self._identity_reader(expected.pid)
        except (ProcessLookupError, PermissionError, OSError):
            return False
        return current == expected
