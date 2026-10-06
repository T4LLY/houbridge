from __future__ import annotations

import json
from typing import Protocol

from houbridge.errors import BridgeError

from .models import TaskRecord
from .store import TaskStore


class CompletionResource(Protocol):
    @property
    def semantic_alias(self) -> str:
        ...


class CompletionResourceStore(Protocol):
    def put_bytes(self, payload: bytes) -> CompletionResource:
        ...


class TaskCompletionResourceFinalizer:
    """Create the exact Task completion Resource before committing completed."""

    def __init__(
        self,
        task_store: TaskStore,
        resource_store: CompletionResourceStore,
    ) -> None:
        self._task_store = task_store
        self._resource_store = resource_store

    def finalize_success(self, task: TaskRecord) -> None:
        stdout = self._task_store.accumulated_stream(task.id, "stdout")
        stderr = self._task_store.accumulated_stream(task.id, "stderr")
        payload = json.dumps(
            {"stdout": stdout, "stderr": stderr},
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        try:
            resource = self._resource_store.put_bytes(payload)
        except BridgeError as exc:
            self._task_store.mark_runtime_failed(
                task.id,
                code="task_resource_finalization_failed",
                message="Task completion Resource could not be created.",
                detail=f"{exc.code}: {exc.message}" + (f" ({exc.detail})" if exc.detail else ""),
            )
            return
        self._task_store.mark_completed(
            task.id,
            completion_resource_id=resource.semantic_alias,
        )
