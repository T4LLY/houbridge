from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from houbridge.errors import BridgeError
from houbridge.history.invocation import HistoryInvocationPreparation
from houbridge.temporary_workspace import TemporaryWorkspace

from .models import TaskRecord


STARTED_MARKER = "started.json"
PYTHON_FINISHED_MARKER = "python-finished.json"
WRAPPER_FAILED_MARKER = "wrapper-failed.json"
COMPLETION_MARKER = "completion.json"
STDOUT_FILE = "stdout.txt"
STDERR_FILE = "stderr.txt"


@dataclass(frozen=True, slots=True)
class TaskCompletion:
    task_id: str
    python_ok: bool


@dataclass(frozen=True, slots=True)
class TaskWrapperFailure:
    task_id: str
    detail: str


@dataclass(frozen=True, slots=True)
class StagedTaskInvocation:
    workspace: TemporaryWorkspace
    request_path: Path
    script_path: Path


def stage_task_request(
    workspace: TemporaryWorkspace,
    task: TaskRecord,
    *,
    history: HistoryInvocationPreparation | None = None,
) -> Path:
    if task.source is None:
        raise BridgeError(
            "task_source_missing",
            f"Task {task.id} no longer has submitted source available for dispatch.",
        )

    source_path = workspace.path_for("source.py")
    source_path.write_text(task.source, encoding="utf-8", newline="")
    request_path = workspace.path_for("request.json")
    request = {
        "task_id": task.id,
        "source_file": str(source_path),
        "source_path": task.file_path,
        "argv": list(task.argv),
        "stdout_file": str(workspace.path_for(STDOUT_FILE)),
        "stderr_file": str(workspace.path_for(STDERR_FILE)),
        "started_marker": str(workspace.path_for(STARTED_MARKER)),
        "python_finished_marker": str(workspace.path_for(PYTHON_FINISHED_MARKER)),
        "wrapper_failed_marker": str(workspace.path_for(WRAPPER_FAILED_MARKER)),
        "completion_marker": str(workspace.path_for(COMPLETION_MARKER)),
    }
    if history is not None:
        request["history"] = {
            "runtime_script": str(history.runtime_script.resolve()),
            "request_file": str(history.request_path.resolve()),
        }
    request_path.write_text(
        json.dumps(request, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
        newline="\n",
    )
    return request_path


def started_marker_exists(workspace: TemporaryWorkspace, task_id: str) -> bool:
    path = workspace.path_for(STARTED_MARKER)
    if not path.exists():
        return False
    payload = _read_marker(path, expected_task_id=task_id)
    if set(payload) != {"version", "task_id"} or payload.get("version") != 1:
        raise BridgeError("task_marker_invalid", f"Task {task_id} started marker is invalid.")
    return True


def python_finished_marker_exists(workspace: TemporaryWorkspace, task_id: str) -> bool:
    path = workspace.path_for(PYTHON_FINISHED_MARKER)
    if not path.exists():
        return False
    payload = _read_marker(path, expected_task_id=task_id)
    if set(payload) != {"version", "task_id", "python_ok"} or payload.get("version") != 1:
        raise BridgeError("task_marker_invalid", f"Task {task_id} Python-finished marker is invalid.")
    if not isinstance(payload.get("python_ok"), bool):
        raise BridgeError("task_marker_invalid", f"Task {task_id} Python-finished marker is invalid.")
    return True


def read_wrapper_failure_marker(
    workspace: TemporaryWorkspace,
    task_id: str,
) -> TaskWrapperFailure | None:
    path = workspace.path_for(WRAPPER_FAILED_MARKER)
    if not path.exists():
        return None
    payload = _read_marker(path, expected_task_id=task_id)
    if set(payload) != {"version", "task_id", "detail"} or payload.get("version") != 1:
        raise BridgeError("task_marker_invalid", f"Task {task_id} wrapper-failed marker is invalid.")
    detail = payload.get("detail")
    if not isinstance(detail, str) or not detail:
        raise BridgeError("task_marker_invalid", f"Task {task_id} wrapper-failed marker is invalid.")
    return TaskWrapperFailure(task_id=task_id, detail=detail)


def read_completion_marker(
    workspace: TemporaryWorkspace,
    task_id: str,
) -> TaskCompletion | None:
    path = workspace.path_for(COMPLETION_MARKER)
    if not path.exists():
        return None
    payload = _read_marker(path, expected_task_id=task_id)
    if set(payload) != {"version", "task_id", "python_ok"} or payload.get("version") != 1:
        raise BridgeError("task_marker_invalid", f"Task {task_id} completion marker is invalid.")
    python_ok = payload.get("python_ok")
    if not isinstance(python_ok, bool):
        raise BridgeError("task_marker_invalid", f"Task {task_id} completion marker is invalid.")
    return TaskCompletion(task_id=task_id, python_ok=python_ok)


def stream_path(workspace: TemporaryWorkspace, stream: str) -> Path:
    if stream == "stdout":
        return workspace.path_for(STDOUT_FILE)
    if stream == "stderr":
        return workspace.path_for(STDERR_FILE)
    raise ValueError("stream must be stdout or stderr")


def _read_marker(path: Path, *, expected_task_id: str) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise BridgeError("task_marker_invalid", f"Task marker is invalid: {path.name}") from exc
    if not isinstance(payload, dict) or payload.get("task_id") != expected_task_id:
        raise BridgeError(
            "task_marker_invalid",
            f"Task marker does not belong to {expected_task_id}: {path.name}",
        )
    return payload
