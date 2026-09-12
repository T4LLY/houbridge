from __future__ import annotations

from pathlib import Path

from houbridge.errors import BridgeError
from houbridge.execution.history import ExecutionHistoryPreparation
from houbridge.execution.models import ExecutionInvocation, ExecutionOutcome
from houbridge.session.resolver import ResolvedSession
from houbridge.temporary_workspace import TemporaryWorkspace

from .invocation import HistoryInvocationPreparation, HistoryInvocationRecorder, ResourceStoreFactory
from .service import HistoryStorageService


SynchronousHistoryPreparation = HistoryInvocationPreparation


class SynchronousExecutionHistory:
    """Synchronous Execution adapter over the shared managed-Python History seam."""

    def __init__(
        self,
        storage: HistoryStorageService,
        *,
        requested_code_profile: str,
        resource_store_factory: ResourceStoreFactory,
        runtime_script: Path | None = None,
    ) -> None:
        self._requested_code_profile = requested_code_profile
        self._recorder = HistoryInvocationRecorder(
            storage,
            resource_store_factory=resource_store_factory,
            runtime_script=runtime_script,
        )

    def prepare(
        self,
        invocation: ExecutionInvocation,
        session: ResolvedSession,
        workspace: TemporaryWorkspace,
    ) -> SynchronousHistoryPreparation:
        return self._recorder.prepare(
            invocation.source,
            session.identity,
            workspace,
            requested_code_profile=self._requested_code_profile,
        )

    def finalize(
        self,
        preparation: ExecutionHistoryPreparation,
        invocation: ExecutionInvocation,
        session: ResolvedSession,
        outcome: ExecutionOutcome,
        workspace: TemporaryWorkspace,
    ) -> None:
        if not isinstance(preparation, HistoryInvocationPreparation):
            raise BridgeError(
                "history_finalize_failed",
                "History preparation does not belong to managed Execution History.",
            )
        if preparation.storage.identity != session.identity:
            raise BridgeError(
                "history_finalize_failed",
                "History preparation target changed before finalization.",
            )
        source_path = Path(invocation.source_path)
        if not source_path.is_absolute():
            source_path = Path(invocation.origin_cwd) / source_path
        self._recorder.finalize(
            preparation,
            cwd=invocation.origin_cwd,
            status="completed" if outcome.python_ok else "failed",
            file=str(source_path),
            args=invocation.argv[1:],
            purpose=invocation.purpose,
        )
