from __future__ import annotations

import contextlib
import json
import os
import runpy
import sys
import traceback
from pathlib import Path


def run(request_path_value: str) -> None:
    """Execute one staged Task with recovery-visible marker ordering."""

    import hou

    request_path = Path(request_path_value)
    request = json.loads(request_path.read_text(encoding="utf-8"))
    task_id = str(request["task_id"])
    source_path = str(request["source_path"])
    source_argv = list(request["argv"])
    with Path(request["source_file"]).open("r", encoding="utf-8", newline="") as stream:
        source = stream.read()

    stdout_path = Path(request["stdout_file"])
    stderr_path = Path(request["stderr_file"])
    started_path = Path(request["started_marker"])
    completion_path = Path(request["completion_marker"])
    python_finished_path = Path(
        request.get("python_finished_marker", completion_path.with_name("python-finished.json"))
    )
    wrapper_failed_path = Path(
        request.get("wrapper_failed_marker", completion_path.with_name("wrapper-failed.json"))
    )

    history_runtime = None
    history_context = None
    history_request = request.get("history")
    if history_request is not None:
        if not isinstance(history_request, dict):
            raise RuntimeError("Task History request must be a JSON object.")
        runtime_script = history_request.get("runtime_script")
        request_file = history_request.get("request_file")
        if not isinstance(runtime_script, str) or not runtime_script:
            raise RuntimeError("Task History runtime script is missing.")
        if not isinstance(request_file, str) or not request_file:
            raise RuntimeError("Task History request file is missing.")
        history_runtime = runpy.run_path(runtime_script)
        # Action baseline establishment is part of pre-start History setup. The
        # started marker must not become visible before this succeeds.
        history_context = history_runtime["prepare"](request_file)

    namespace = {
        "__name__": "__main__",
        "__file__": source_path,
        "hou": hou,
    }
    python_ok = False
    caller_finished = False

    try:
        with stdout_path.open("w", encoding="utf-8", newline="") as stdout_file, stderr_path.open(
            "w", encoding="utf-8", newline=""
        ) as stderr_file:
            previous_argv = sys.argv
            try:
                sys.argv = source_argv
                # Caller Python can only begin after this marker has been fully
                # flushed and atomically published.
                _atomic_write_json(started_path, {"version": 1, "task_id": task_id})
                with contextlib.redirect_stdout(stdout_file), contextlib.redirect_stderr(stderr_file):
                    try:
                        exec(compile(source, source_path, "exec"), namespace, namespace)
                    except BaseException:
                        caller_finished = True
                        _atomic_write_json(
                            python_finished_path,
                            {"version": 1, "task_id": task_id, "python_ok": False},
                        )
                        traceback.print_exc(file=stderr_file)
                    else:
                        python_ok = True
                        caller_finished = True
                        _atomic_write_json(
                            python_finished_path,
                            {"version": 1, "task_id": task_id, "python_ok": True},
                        )
            finally:
                sys.argv = previous_argv
                _flush_file(stdout_file)
                _flush_file(stderr_file)

        if history_runtime is not None and history_context is not None:
            try:
                history_runtime["finalize"](history_context)
            except Exception:
                # Caller Python already reached a terminal outcome. History capture
                # failure must not redefine it or trigger replay.
                pass

        # Completion becomes visible only after both transport streams and the
        # best-effort History capture have reached their terminal state.
        _atomic_write_json(
            completion_path,
            {"version": 1, "task_id": task_id, "python_ok": python_ok},
        )
    except BaseException as exc:
        if caller_finished:
            _publish_wrapper_failure_best_effort(wrapper_failed_path, task_id, exc)
        raise


def _publish_wrapper_failure_best_effort(path: Path, task_id: str, exc: BaseException) -> None:
    detail = f"{type(exc).__name__}: {exc}"
    if len(detail) > 4096:
        detail = detail[:4096] + "…"
    try:
        _atomic_write_json(
            path,
            {"version": 1, "task_id": task_id, "detail": detail},
        )
    except BaseException:
        # Preserve the original wrapper failure. The host can still detect an
        # exited hcommand after the Python-finished marker when this write fails.
        pass


def _flush_file(stream) -> None:
    stream.flush()
    os.fsync(stream.fileno())


def _atomic_write_json(path: Path, payload: object) -> None:
    staging = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with staging.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, ensure_ascii=False, separators=(",", ":"))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(staging, path)
    finally:
        try:
            staging.unlink()
        except FileNotFoundError:
            pass
