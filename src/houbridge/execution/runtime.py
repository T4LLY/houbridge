from __future__ import annotations

from houbridge.houdini.transport import HoudiniTransport
from houbridge.process_coordination import ManagedExecutionLock
from houbridge.session.resolver import ResolvedSession
from houbridge.temporary_workspace import TemporaryWorkspaceService

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
    ) -> None:
        self._transport = transport
        self._workspaces = workspaces
        self._execution_lock = execution_lock
        self._lock_timeout_seconds = lock_timeout_seconds
        self._script_builder = script_builder or ExecutionScriptBuilder()

    def execute(
        self,
        session: ResolvedSession,
        invocation: ExecutionInvocation,
    ) -> ExecutionOutcome:
        validate_python_source(invocation.source)
        workspace = self._workspaces.allocate(prefix="exec")
        try:
            request_path = stage_invocation(workspace, invocation)
            staged = self._script_builder.stage(workspace, request_path)
            with self._execution_lock.acquire(
                session.identity,
                timeout_seconds=self._lock_timeout_seconds,
            ):
                # Transport BridgeError is intentionally allowed to propagate. A
                # failed hcommand invocation must never be reinterpreted as a
                # successful Python outcome.
                self._transport.execute_script(session.target, staged.script_path)
                return collect_outcome(workspace)
        finally:
            workspace.remove()
