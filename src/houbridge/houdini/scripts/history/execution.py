from __future__ import annotations

import json
import os
import runpy
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(slots=True)
class HistoryCaptureContext:
    recorder: object
    capture_path: Path
    started_at: str


def prepare(request_path_value: str) -> HistoryCaptureContext:
    """Install lifecycle tracking and establish the Action baseline before Python."""

    request_path = Path(request_path_value)
    request = json.loads(request_path.read_text(encoding="utf-8"))
    database_path = str(Path(_required_string(request, "database_path")).resolve())
    database_lock_path = str(
        Path(_required_string(request, "database_lock_path")).resolve()
    )
    capture_path = Path(_required_string(request, "capture_file"))
    lock_timeout_seconds = _positive_number(request.get("lock_timeout_seconds", 120.0))

    script_dir = Path(__file__).resolve().parent
    lifecycle = runpy.run_path(str(script_dir / "lifecycle.py"))
    lifecycle["install"](database_path, database_lock_path, lock_timeout_seconds)
    def generation_getter() -> int:
        return int(lifecycle["current_generation"](database_path))

    recorder_runtime = runpy.run_path(str(script_dir / "action_recorder.py"))
    recorder = recorder_runtime["ActionRecorder"](
        scene_generation_getter=generation_getter,
    )
    return HistoryCaptureContext(
        recorder=recorder,
        capture_path=capture_path,
        started_at=datetime.now(timezone.utc).isoformat(),
    )


def finalize(context: HistoryCaptureContext) -> None:
    """Publish only compact recorder output; History persistence stays host-side."""

    raw_changes = context.recorder.finalize()
    scene_replaced = raw_changes is None
    payload = {
        "time": context.started_at,
        "scene_replaced": scene_replaced,
        "changes": [] if scene_replaced else raw_changes,
    }
    _atomic_write_json(context.capture_path, payload)


def close(context: HistoryCaptureContext) -> None:
    """Release this invocation's recorder callbacks without finalizing capture."""

    context.recorder.close()


def _required_string(payload: object, key: str) -> str:
    if not isinstance(payload, dict):
        raise RuntimeError("History execution request must be a JSON object.")
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise RuntimeError(f"History execution request is missing {key}.")
    return value


def _positive_number(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RuntimeError("History execution request has invalid lock_timeout_seconds.")
    parsed = float(value)
    if parsed <= 0 or parsed == float("inf") or parsed == float("-inf") or parsed != parsed:
        raise RuntimeError("History execution request has invalid lock_timeout_seconds.")
    return parsed


def _atomic_write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    staging = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        staging.write_text(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
            newline="\n",
        )
        os.replace(staging, path)
    finally:
        try:
            staging.unlink()
        except FileNotFoundError:
            pass
