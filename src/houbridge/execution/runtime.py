from __future__ import annotations

from houbridge.houdini.transport import HoudiniTransport
from houbridge.process_coordination import ManagedExecutionLock
from houbridge.session.resolver import ResolvedSession
from houbridge.temporary_workspace import TemporaryWorkspaceService

from .history import ExecutionHistoryBoundary
from .models import ExecutionInvocation, ExecutionOutcome
from .script import ExecutionScriptBuilder
from .source import validate_python_source
from .workspace import collect_outcome, stage_invocation


class ExecutionRuntime:
    """Invocation-local synchronous managed Python execution orchestration."""

    def __init__(
        self,
        *,
        transport: HoudiniTransport,
        workspaces: TemporaryWorkspaceService,
        execution_lock: ManagedExecutionLock,
        lock_timeout_seconds: float,
        script_builder: ExecutionScriptBuilder | None = None,
        history: ExecutionHistoryBoundary | None = None,
    ) -> None:
        self._transport = transport
        self._workspaces = workspaces
        self._execution_lock = execution_lock
        self._lock_timeout_seconds = lock_timeout_seconds
        self._script_builder = script_builder or ExecutionScriptBuilder()
        self._history = history

    def execute(
        self,
        session: ResolvedSession,
        invocation: ExecutionInvocation,
    ) -> ExecutionOutcome:
        validate_python_source(invocation.source)
        workspace = self._workspaces.allocate(prefix="exec")
        try:
            with self._execution_lock.acquire(
                session.identity,
                timeout_seconds=self._lock_timeout_seconds,
            ):
                history_preparation = (
                    None
                    if self._history is None
                    else self._history.prepare(invocation, session, workspace)
                )
                request_path = stage_invocation(
                    workspace,
                    invocation,
                    history=history_preparation,
                )
                staged = self._script_builder.stage(workspace, request_path)
                # Transport BridgeError is intentionally allowed to propagate. A
                # failed hcommand invocation must never be reinterpreted as a
                # successful Python outcome.
                self._transport.execute_script(session.target, staged.script_path)
                outcome = collect_outcome(workspace)
                if self._history is not None and history_preparation is not None:
                    try:
                        self._history.finalize(
                            history_preparation,
                            invocation,
                            session,
                            outcome,
                            workspace,
                        )
                    except Exception:
                        # Caller Python has already reached its terminal outcome.
                        # History persistence failure must never replay or redefine it.
                        pass
                return outcome
        finally:
            workspace.remove()
