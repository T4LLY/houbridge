from __future__ import annotations

from pathlib import Path
from typing import Protocol

from houbridge.errors import BridgeError
from houbridge.history.invocation import HistoryInvocationPreparation, HistoryInvocationRecorder
from houbridge.history.service import HistoryStorageService
from houbridge.resource.store import ResourceStore
from houbridge.temporary_workspace import TemporaryWorkspace

from .models import TaskRecord


class TaskHistoryBoundary(Protocol):
    """Task-owned seam for optional Action History integration."""

    def prepare(
        self,
        task: TaskRecord,
        workspace: TemporaryWorkspace,
    ) -> HistoryInvocationPreparation | None: ...

    def finalize(
        self,
        task: TaskRecord,
        workspace: TemporaryWorkspace,
        *,
        python_ok: bool,
    ) -> None: ...


class AsyncTaskHistory:
    """Adapter from frozen Task context to the shared managed-Python History seam."""

    def __init__(
        self,
        storage: HistoryStorageService,
        *,
        resource_store: ResourceStore,
        runtime_script: Path | None = None,
    ) -> None:
        self._recorder = HistoryInvocationRecorder(
            storage,
            resource_store_factory=lambda: resource_store,
            runtime_script=runtime_script,
        )

    def prepare(
        self,
        task: TaskRecord,
        workspace: TemporaryWorkspace,
    ) -> HistoryInvocationPreparation | None:
        if not task.history_enabled:
            return None
        if task.source is None:
            raise BridgeError(
                "history_preflight_failed",
                f"Task {task.id} no longer has source available for History preflight.",
            )
        return self._recorder.prepare(
            task.source,
            task.dispatch.process_identity,
            workspace,
            requested_code_profile=task.history_code_profile,
        )

    def finalize(
        self,
        task: TaskRecord,
        workspace: TemporaryWorkspace,
        *,
        python_ok: bool,
    ) -> None:
        if not task.history_enabled:
            return
        preparation = self._recorder.resume(
            task.dispatch.process_identity,
            workspace,
            source_hash=task.source_sha256,
        )
        self._recorder.finalize(
            preparation,
            cwd=task.origin_cwd,
            status="completed" if python_ok else "failed",
            file=task.file_path,
            args=task.argv[1:],
            purpose=task.purpose,
            # Task IDs are reusable after `task reset`; the invocation-local
            # workspace stays stable across recovery but differs for new runs.
            execution_key=f"task:{task.id}:{workspace.directory.resolve()}",
        )
