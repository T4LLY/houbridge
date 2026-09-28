from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Protocol

from houbridge.errors import BridgeError
from houbridge.houdini.transport import HoudiniTarget, HoudiniTransport
from houbridge.process_coordination import ProcessIdentity, process_identity_for_pid
from houbridge.temporary_workspace import TemporaryWorkspace, TemporaryWorkspaceService

from .history import TaskHistoryBoundary
from .invocation_store import TaskInvocationState, TaskInvocationStore
from .models import TaskRecord
from .script import TaskScriptBuilder
from .store import TaskStore
from .streaming import TaskStreamCollector
from .workspace import (
    TaskCompletion,
    python_finished_marker_exists,
    read_completion_marker,
    read_wrapper_failure_marker,
    stage_task_request,
    started_marker_exists,
)


class RunningDispatch(Protocol):
    def poll(self) -> int | None:
        ...

    def terminate(self) -> None:
        ...


class TaskDispatcher(Protocol):
    def start(self, task: TaskRecord, script_path: Path) -> RunningDispatch:
        ...


class TaskSuccessFinalizer(Protocol):
    """Phase 19 boundary: create the completion Resource, then commit completed."""

    def finalize_success(self, task: TaskRecord) -> None:
        ...


class FrozenTaskDispatcher:
    """Dispatch through the submission-time frozen hcommand context."""

    def start(self, task: TaskRecord, script_path: Path) -> RunningDispatch:
        dispatch = task.dispatch
        transport = HoudiniTransport(
            dispatch.transport_executable,
            timeout_seconds=dispatch.transport_timeout_seconds,
            environ=dispatch.transport_environment,
        )
        return transport.start_script(
            HoudiniTarget(host="127.0.0.1", port=dispatch.port),
            script_path,
        )


class TaskInvocationRunner:
    """Run/recover one Task invocation without ever replaying a staged dispatch."""

    def __init__(
        self,
        store: TaskStore,
        invocations: TaskInvocationStore,
        workspaces: TemporaryWorkspaceService,
        success_finalizer: TaskSuccessFinalizer,
        *,
        history: TaskHistoryBoundary | None = None,
        dispatcher: TaskDispatcher | None = None,
        script_builder: TaskScriptBuilder | None = None,
        identity_reader: Callable[[int], ProcessIdentity] = process_identity_for_pid,
        sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], datetime] | None = None,
        poll_interval_seconds: float = 0.05,
    ) -> None:
        if poll_interval_seconds <= 0:
            raise ValueError("poll_interval_seconds must be > 0")
        self._store = store
        self._invocations = invocations
        self._workspaces = workspaces
        self._success_finalizer = success_finalizer
        self._history = history
        self._dispatcher = dispatcher or FrozenTaskDispatcher()
        self._script_builder = script_builder or TaskScriptBuilder()
        self._identity_reader = identity_reader
        self._sleep = sleep
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._poll_interval_seconds = poll_interval_seconds
        self._streams = TaskStreamCollector(invocations)

    def run(self, task: TaskRecord) -> None:
        workspace = self._workspaces.allocate(prefix="task")
        state = self._invocations.create(task.id, workspace.directory)
        try:
            history_preparation = self._prepare_history(task, workspace)
            request_path = stage_task_request(
                workspace,
                task,
                history=history_preparation,
            )
            staged = self._script_builder.stage(workspace, request_path)
            dispatch = self._dispatcher.start(task, staged.script_path)
        except BridgeError as exc:
            self.runtime_failed(task, exc)
            return
        except (OSError, UnicodeError, ValueError) as exc:
            self.runtime_failed(
                task,
                BridgeError(
                    "task_dispatch_failed",
                    f"Task {task.id} dispatch could not be staged.",
                    f"{type(exc).__name__}: {exc}",
                ),
            )
            return
        self._monitor(task, state, workspace, dispatch)

    def recover(self, task: TaskRecord) -> None:
        state = self._invocations.get(task.id)
        if state is None:
            self.runtime_failed(
                task,
                BridgeError(
                    "task_invocation_missing",
                    f"Task {task.id} has no invocation state to recover.",
                ),
            )
            return
        try:
            workspace = self._workspaces.open_existing(state.workspace_path)
        except (FileNotFoundError, ValueError) as exc:
            self.runtime_failed(
                task,
                BridgeError(
                    "task_workspace_missing",
                    f"Task {task.id} recovery workspace is unavailable.",
                    str(exc),
                ),
            )
            return
        self._monitor(task, state, workspace, None)

    def runtime_failed(self, task: TaskRecord, error: BridgeError) -> None:
        state = self._invocations.get(task.id)
        if state is not None:
            try:
                workspace = self._workspaces.open_existing(state.workspace_path)
            except (FileNotFoundError, ValueError):
                workspace = None
            if workspace is not None:
                try:
                    self._streams.drain(task.id, workspace, final=False)
                except BridgeError:
                    # Runtime failure is already authoritative. Stream recovery is
                    # best-effort here and must not prevent terminalization/cleanup.
                    pass
        current = self._store.get(task.id)
        if current is not None and current.status not in ("completed", "failed"):
            self._store.mark_runtime_failed(
                task.id,
                code=error.code,
                message=error.message,
                detail=error.detail,
            )
        self._cleanup_invocation(task.id)

    def cleanup_terminal_workspaces(self) -> None:
        for state in self._invocations.terminal_states():
            self._cleanup_invocation(state.task_id)

    def _monitor(
        self,
        task: TaskRecord,
        state: TaskInvocationState,
        workspace: TemporaryWorkspace,
        dispatch: RunningDispatch | None,
    ) -> None:
        started = self._observe_started(task, workspace)
        dispatch_deadline = _parse_utc(state.dispatch_started_at) + timedelta(
            seconds=task.dispatch.transport_timeout_seconds
        )
        while not started:
            completion = read_completion_marker(workspace, task.id)
            if completion is not None:
                self.runtime_failed(
                    task,
                    BridgeError(
                        "task_marker_invalid",
                        f"Task {task.id} completion marker appeared before its started marker.",
                    ),
                )
                return
            if dispatch is not None:
                returncode = dispatch.poll()
                if returncode is not None:
                    if self._observe_started(task, workspace):
                        started = True
                        break
                    self.runtime_failed(
                        task,
                        BridgeError(
                            "houdini_transport_failed",
                            f"hcommand exited before Task {task.id} started.",
                            f"status={returncode}",
                        ),
                    )
                    return
            if not self._target_is_current(task):
                self.runtime_failed(task, _target_changed(task))
                return
            if _as_utc(self._now()) >= dispatch_deadline:
                if self._observe_started(task, workspace):
                    started = True
                    break
                if dispatch is not None:
                    dispatch.terminate()
                self.runtime_failed(
                    task,
                    BridgeError(
                        "task_dispatch_timeout",
                        f"Task {task.id} did not establish execution before the transport timeout.",
                    ),
                )
                return
            self._sleep(self._poll_interval_seconds)
            started = self._observe_started(task, workspace)

        while True:
            self._streams.drain(task.id, workspace, final=False)
            completion = read_completion_marker(workspace, task.id)
            if completion is not None:
                self._streams.drain(task.id, workspace, final=True)
                self._finalize(task.id, completion, workspace)
                return

            wrapper_failure = read_wrapper_failure_marker(workspace, task.id)
            if wrapper_failure is not None:
                self.runtime_failed(task, _wrapper_failed(task, wrapper_failure.detail))
                return

            if dispatch is not None and python_finished_marker_exists(workspace, task.id):
                returncode = dispatch.poll()
                if returncode is not None:
                    completion = read_completion_marker(workspace, task.id)
                    if completion is not None:
                        self._streams.drain(task.id, workspace, final=True)
                        self._finalize(task.id, completion, workspace)
                        return
                    wrapper_failure = read_wrapper_failure_marker(workspace, task.id)
                    if wrapper_failure is not None:
                        self.runtime_failed(task, _wrapper_failed(task, wrapper_failure.detail))
                    else:
                        self.runtime_failed(
                            task,
                            _wrapper_failed(
                                task,
                                f"hcommand exited after caller Python finished with status={returncode}",
                            ),
                        )
                    return

            if not self._target_is_current(task):
                completion = read_completion_marker(workspace, task.id)
                if completion is not None:
                    self._streams.drain(task.id, workspace, final=True)
                    self._finalize(task.id, completion, workspace)
                else:
                    self.runtime_failed(task, _target_changed(task))
                return
            self._sleep(self._poll_interval_seconds)

    def _observe_started(self, task: TaskRecord, workspace: TemporaryWorkspace) -> bool:
        if not started_marker_exists(workspace, task.id):
            return False
        current = self._store.get(task.id)
        if current is None:
            raise BridgeError("task_not_found", f"Task does not exist: {task.id}")
        if current.status == "queued":
            self._store.mark_running(task.id)
        elif current.status != "running":
            raise BridgeError(
                "task_state_conflict",
                f"Task {task.id} started marker conflicts with terminal status {current.status}.",
            )
        return True

    def _finalize(
        self,
        task_id: str,
        completion: TaskCompletion,
        workspace: TemporaryWorkspace,
    ) -> None:
        task = self._store.get(task_id)
        if task is None:
            raise BridgeError("task_not_found", f"Task does not exist: {task_id}")
        if task.history_enabled and self._history is not None:
            try:
                self._history.finalize(task, workspace, python_ok=completion.python_ok)
            except Exception:
                # Caller Python has already reached its terminal outcome. History
                # persistence must never redefine it or cause Task replay.
                pass
        if completion.python_ok:
            self._success_finalizer.finalize_success(task)
        else:
            self._store.mark_python_failed(task_id)
        terminal = self._store.get(task_id)
        if terminal is None or terminal.status not in ("completed", "failed"):
            raise BridgeError(
                "task_runtime_protocol",
                f"Task {task_id} terminal finalizer returned without committing terminal state.",
            )
        self._cleanup_invocation(task_id)

    def _prepare_history(
        self,
        task: TaskRecord,
        workspace: TemporaryWorkspace,
    ):
        if not task.history_enabled:
            return None
        if self._history is None:
            raise BridgeError(
                "history_preflight_failed",
                f"Task {task.id} enabled History but no History boundary is available.",
            )
        try:
            return self._history.prepare(task, workspace)
        except BridgeError:
            raise
        except Exception as exc:
            raise BridgeError(
                "history_preflight_failed",
                f"Task {task.id} History preflight failed.",
                f"{type(exc).__name__}: {exc}",
            ) from exc

    def _target_is_current(self, task: TaskRecord) -> bool:
        try:
            return self._identity_reader(task.dispatch.pid) == task.dispatch.process_identity
        except (ProcessLookupError, PermissionError, OSError):
            return False

    def _cleanup_invocation(self, task_id: str) -> None:
        state = self._invocations.get(task_id)
        if state is None:
            return
        try:
            workspace = self._workspaces.open_existing(state.workspace_path)
        except FileNotFoundError:
            workspace = None
        except ValueError as exc:
            raise BridgeError(
                "task_workspace_invalid",
                f"Task {task_id} workspace is outside the managed Temporary Workspace root.",
                str(exc),
            ) from exc
        if workspace is not None:
            workspace.remove()
        self._invocations.remove(task_id)


def _wrapper_failed(task: TaskRecord, detail: str) -> BridgeError:
    return BridgeError(
        "task_wrapper_failed",
        f"Task {task.id} execution wrapper failed after caller Python finished.",
        detail,
    )


def _target_changed(task: TaskRecord) -> BridgeError:
    return BridgeError(
        "task_target_changed",
        f"Task {task.id} target changed while managed execution was active.",
    )


def _parse_utc(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise BridgeError(
            "task_store_invalid",
            "Stored Task invocation timestamp is invalid.",
            value,
        ) from exc
    return _as_utc(parsed)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("Task runtime clock must return a timezone-aware datetime")
    return value.astimezone(timezone.utc)
