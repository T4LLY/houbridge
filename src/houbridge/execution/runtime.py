from __future__ import annotations

from houbridge.errors import BridgeError
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
                try:
                    self._transport.execute_script(session.target, staged.script_path)
                except BridgeError as exc:
                    if not (
                        exc.code == "hcommand_timeout"
                        and history_preparation is not None
                        and workspace.path_for("execution.json").is_file()
                    ):
                        # A transport failure before the terminal caller marker, or
                        # without enabled History, remains a transport failure.
                        raise
                    # The injected wrapper publishes execution.json only after
                    # caller Python and its output files are terminal, and before
                    # best-effort History finalization. A timeout after that marker
                    # therefore must not redefine the caller's Python outcome.
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
