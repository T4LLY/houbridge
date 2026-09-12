from __future__ import annotations

from collections.abc import Callable
from typing import Any

from houbridge.errors import BridgeError

from .presentation import task_get_payload, task_list_item
from .store import TaskStore
from .supervisor import TaskRuntimeSupervisor


class TaskCommandService:
    """Public Task read/reset contract over one configured global Task store."""

    def __init__(
        self,
        store: TaskStore,
        supervisor: TaskRuntimeSupervisor,
        runtime_launcher: Callable[[str], None],
        *,
        ttl_hours: int,
    ) -> None:
        if ttl_hours < 1:
            raise ValueError("ttl_hours must be >= 1")
        self._store = store
        self._supervisor = supervisor
        self._runtime_launcher = runtime_launcher
        self._ttl_hours = ttl_hours

    def get(self, task_id: str) -> dict[str, Any]:
        self._prepare()
        task = self._store.get(task_id)
        if task is None:
            raise BridgeError("task_not_found", f"Task does not exist: {task_id}")
        return task_get_payload(self._store, task)

    def list(self) -> dict[str, Any]:
        self._prepare()
        return {"tasks": [task_list_item(task) for task in self._store.list_tasks()]}

    def reset(self) -> dict[str, Any]:
        self._prepare()
        self._store.reset()
        return {}

    def _prepare(self) -> None:
        self._store.cleanup_expired(ttl_hours=self._ttl_hours)
        self._supervisor.ensure_active(self._runtime_launcher)
