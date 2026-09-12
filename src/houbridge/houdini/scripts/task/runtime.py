from __future__ import annotations

import contextlib
import json
import os
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

    namespace = {
        "__name__": "__main__",
        "__file__": source_path,
        "hou": hou,
    }
    python_ok = False

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
                    traceback.print_exc(file=stderr_file)
                else:
                    python_ok = True
        finally:
            sys.argv = previous_argv
            _flush_file(stdout_file)
            _flush_file(stderr_file)

    # Completion becomes visible only after both transport streams have been
    # flushed. It is emitted for Python success and Python failure alike.
    _atomic_write_json(
        completion_path,
        {"version": 1, "task_id": task_id, "python_ok": python_ok},
    )


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
