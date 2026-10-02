from __future__ import annotations

from collections.abc import Callable

from houbridge.errors import BridgeError
from houbridge.execution.models import ExecutionInvocation
from houbridge.houdini.transport import HoudiniTransport
from houbridge.session.resolver import SessionResolver

from .store import TaskStore
from .submission import freeze_task_submission
from .supervisor import TaskRuntimeSupervisor


class AsyncExecutionSubmitter:
    """Persist one frozen Task and establish on-demand runtime handoff."""

    def __init__(
        self,
        resolver: SessionResolver,
        transport: HoudiniTransport,
        store: TaskStore,
        supervisor: TaskRuntimeSupervisor,
        runtime_launcher: Callable[[str], None],
        *,
        lock_timeout_seconds: float,
        history_enabled: bool,
        history_code_profile: str,
        ttl_hours: int,
    ) -> None:
        self._resolver = resolver
        self._transport = transport
        self._store = store
        self._supervisor = supervisor
        self._runtime_launcher = runtime_launcher
        self._lock_timeout_seconds = lock_timeout_seconds
        self._history_enabled = history_enabled
        self._history_code_profile = history_code_profile
        self._ttl_hours = ttl_hours

    def submit(
        self,
        invocation: ExecutionInvocation,
        *,
        session: int | None,
    ) -> str:
        resolved = self._resolver.resolve(session)
        submission = freeze_task_submission(
            invocation,
            session=resolved,
            transport=self._transport,
            lock_timeout_seconds=self._lock_timeout_seconds,
            history_enabled=self._history_enabled,
            history_code_profile=self._history_code_profile,
        )
        self._store.cleanup_expired(ttl_hours=self._ttl_hours)
        task = self._store.submit(submission)
        try:
            self._supervisor.ensure_active(self._runtime_launcher)
        except BridgeError as exc:
            current = self._store.get(task.id)
            if (
                exc.code
                in ("task_runtime_handoff_failed", "task_runtime_handoff_timeout")
                and current is not None
                and current.status in ("running", "completed", "failed")
            ):
                # Persisted Task state proves the runtime accepted this Task,
                # even if it retired before the parent observed its handoff.
                return task.id
            if current is not None and current.status in ("queued", "running"):
                self._store.mark_runtime_failed(
                    task.id,
                    code="task_runtime_handoff_failed",
                    message="Task Runtime handoff could not be established.",
                    detail=f"{exc.code}: {exc.message}" + (f" ({exc.detail})" if exc.detail else ""),
                )
            raise
        return task.id
