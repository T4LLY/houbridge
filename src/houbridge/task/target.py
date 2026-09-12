from __future__ import annotations

from typing import Callable, Protocol

from houbridge.errors import BridgeError
from houbridge.houdini.transport import HoudiniTransport
from houbridge.process_coordination import ProcessIdentity, process_identity_for_pid
from houbridge.session.probe import SessionProbe, SessionProbeResult

from .models import FrozenDispatchContext, TaskRecord


class DispatchProbe(Protocol):
    def __call__(self, dispatch: FrozenDispatchContext) -> SessionProbeResult:
        ...


class TaskTargetValidator:
    """Validate the exact submission-time Houdini process before dispatch/recovery."""

    def __init__(
        self,
        *,
        probe: DispatchProbe | None = None,
        identity_reader: Callable[[int], ProcessIdentity] = process_identity_for_pid,
    ) -> None:
        self._probe = probe or _probe_frozen_dispatch
        self._identity_reader = identity_reader

    def validate(self, task: TaskRecord) -> None:
        expected = task.dispatch.process_identity
        before = self._read_identity(expected)
        probe = self._probe(task.dispatch)
        if probe.pid != expected.pid:
            raise _target_changed(task, "the bound port belongs to a different Houdini PID")
        if task.dispatch.port not in probe.open_ports:
            raise _target_changed(task, "the bound openport is no longer reported by Houdini")
        after = self._read_identity(expected)
        if before != after:
            raise _target_changed(task, "the process incarnation changed during validation")

    def _read_identity(self, expected: ProcessIdentity) -> ProcessIdentity:
        try:
            current = self._identity_reader(expected.pid)
        except (ProcessLookupError, PermissionError, OSError) as exc:
            raise _target_changed_from_identity(expected, "the bound PID is no longer reachable") from exc
        if current != expected:
            raise _target_changed_from_identity(expected, "the bound PID was reused or restarted")
        return current


def _probe_frozen_dispatch(dispatch: FrozenDispatchContext) -> SessionProbeResult:
    transport = HoudiniTransport(
        dispatch.transport_executable,
        timeout_seconds=dispatch.transport_timeout_seconds,
        environ=dispatch.transport_environment,
    )
    return SessionProbe(lambda: transport).inspect(dispatch.port)


def _target_changed(task: TaskRecord, detail: str) -> BridgeError:
    return BridgeError(
        "task_target_changed",
        f"Task {task.id} target changed before execution could continue.",
        detail,
    )


def _target_changed_from_identity(expected: ProcessIdentity, detail: str) -> BridgeError:
    return BridgeError(
        "task_target_changed",
        f"Bound Houdini PID {expected.pid} no longer matches the submitted process incarnation.",
        detail,
    )
