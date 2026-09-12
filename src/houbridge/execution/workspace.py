from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from houbridge.temporary_workspace import TemporaryWorkspace

from .history import ExecutionHistoryPreparation
from .models import DeclaredResult, ExecutionInvocation, ExecutionOutcome


@dataclass(frozen=True, slots=True)
class StagedExecution:
    workspace: TemporaryWorkspace
    script_path: Path
    request_path: Path


def stage_invocation(
    workspace: TemporaryWorkspace,
    invocation: ExecutionInvocation,
    *,
    history: ExecutionHistoryPreparation | None = None,
) -> Path:
    source_path = workspace.path_for("source.py")
    with source_path.open("w", encoding="utf-8", newline="") as stream:
        stream.write(invocation.source)

    request_path = workspace.path_for("request.json")
    request = {
        "source_file": str(source_path),
        "source_path": invocation.source_path,
        "argv": list(invocation.argv),
        "purpose": invocation.purpose,
        "stdout_file": str(workspace.path_for("stdout.txt")),
        "stderr_file": str(workspace.path_for("stderr.txt")),
        "traceback_file": str(workspace.path_for("traceback.txt")),
        "result_json_file": str(workspace.path_for("result.json")),
        "result_text_file": str(workspace.path_for("result.txt")),
        "status_file": str(workspace.path_for("execution.json")),
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


def collect_outcome(workspace: TemporaryWorkspace) -> ExecutionOutcome:
    status_path = workspace.path_for("execution.json")
    try:
        status = json.loads(status_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("Houdini execution did not publish a valid completion status.") from exc

    if not isinstance(status, dict):
        raise RuntimeError("Houdini execution completion status must be a JSON object.")
    python_ok = status.get("python_ok")
    result_kind = status.get("result_kind")
    if not isinstance(python_ok, bool) or result_kind not in {None, "json", "text"}:
        raise RuntimeError("Houdini execution completion status is invalid.")

    stdout = _read_optional_text(workspace.path_for("stdout.txt"))
    stderr = _read_optional_text(workspace.path_for("stderr.txt"))
    traceback_text = _read_optional_text(workspace.path_for("traceback.txt")) or None

    result: DeclaredResult | None = None
    if python_ok and result_kind == "json":
        result = DeclaredResult("json", workspace.path_for("result.json").read_bytes())
    elif python_ok and result_kind == "text":
        result = DeclaredResult("text", workspace.path_for("result.txt").read_bytes())

    if python_ok and traceback_text is not None:
        raise RuntimeError("Successful Houdini execution unexpectedly published a traceback.")
    if not python_ok and result_kind is not None:
        raise RuntimeError("Failed Houdini execution unexpectedly published a declared result.")

    return ExecutionOutcome(
        python_ok=python_ok,
        result=result,
        stdout=stdout,
        stderr=stderr,
        traceback=traceback_text,
    )


def _read_optional_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""
