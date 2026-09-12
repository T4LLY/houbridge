from __future__ import annotations

from typing import Any

from houbridge.errors import BridgeError

from .models import TaskRecord
from .store import TaskStore


def task_get_payload(store: TaskStore, task: TaskRecord) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": task.id,
        "status": task.status,
        "file": task.file_path,
        "args": list(task.argv),
    }
    if task.status == "queued":
        return payload

    payload["stdout"] = store.accumulated_stream(task.id, "stdout")
    payload["stderr"] = store.accumulated_stream(task.id, "stderr")

    if task.status == "completed":
        if task.completion_resource_id is None:
            raise BridgeError(
                "task_store_invalid",
                f"Completed Task has no completion Resource: {task.id}",
            )
        payload["resource"] = task.completion_resource_id
    elif task.status == "failed" and task.runtime_failure_code is not None:
        payload["error"] = {
            "code": task.runtime_failure_code,
            "message": task.runtime_failure_message or "Task Runtime failed.",
        }
    return payload


def task_list_item(task: TaskRecord) -> dict[str, Any]:
    return {
        "id": task.id,
        "status": task.status,
        "file": task.file_path,
        "args": list(task.argv),
    }
