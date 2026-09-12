from __future__ import annotations

import contextlib
import json
import os
import reprlib
import sys
import traceback
from pathlib import Path


def run(request_path_value: str) -> None:
    """Run one staged caller source inside Houdini and publish bounded metadata."""

    import hou

    request_path = Path(request_path_value)
    request = json.loads(request_path.read_text(encoding="utf-8"))
    with Path(request["source_file"]).open("r", encoding="utf-8", newline="") as source_file:
        source = source_file.read()
    source_path = request["source_path"]
    source_argv = request["argv"]

    stdout_path = Path(request["stdout_file"])
    stderr_path = Path(request["stderr_file"])
    traceback_path = Path(request["traceback_file"])
    result_json_path = Path(request["result_json_file"])
    result_text_path = Path(request["result_text_file"])
    status_path = Path(request["status_file"])

    status: dict[str, object] = {"python_ok": False, "result_kind": None}
    namespace = {
        "__name__": "__main__",
        "__file__": source_path,
        # Preserve the useful native-Houdini execution convenience from the
        # previous runtime without importing any History behavior.
        "hou": hou,
    }

    with stdout_path.open("w", encoding="utf-8", newline="") as stdout_file, stderr_path.open(
        "w", encoding="utf-8", newline=""
    ) as stderr_file:
        previous_argv = sys.argv
        try:
            sys.argv = list(source_argv)
            with contextlib.redirect_stdout(stdout_file), contextlib.redirect_stderr(stderr_file):
                exec(compile(source, source_path, "exec"), namespace, namespace)
        except BaseException:
            with traceback_path.open("w", encoding="utf-8", newline="") as traceback_file:
                traceback.print_exc(file=traceback_file)
        else:
            status["python_ok"] = True
            if "result" in namespace:
                result_kind = _write_declared_result(
                    namespace["result"],
                    result_json_path=result_json_path,
                    result_text_path=result_text_path,
                )
                status["result_kind"] = result_kind
        finally:
            sys.argv = previous_argv

    _atomic_write_json(status_path, status)


def _write_declared_result(
    value: object,
    *,
    result_json_path: Path,
    result_text_path: Path,
) -> str:
    if isinstance(value, str):
        try:
            json.loads(value, parse_constant=_reject_non_finite_json_constant)
        except (json.JSONDecodeError, ValueError, RecursionError):
            result_text_path.write_text(value, encoding="utf-8", newline="")
            return "text"
        result_json_path.write_text(value, encoding="utf-8", newline="")
        return "json"

    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        )
    except (TypeError, ValueError, OverflowError, RecursionError):
        result_text_path.write_text(_bounded_repr(value), encoding="utf-8", newline="")
        return "text"

    result_json_path.write_text(encoded, encoding="utf-8", newline="")
    return "json"


def _bounded_repr(value: object) -> str:
    try:
        return reprlib.repr(value)
    except BaseException:
        value_type = type(value)
        return f"<{value_type.__module__}.{value_type.__qualname__} object>"


def _atomic_write_json(path: Path, payload: object) -> None:
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


def _reject_non_finite_json_constant(_value: str) -> None:
    raise ValueError("Non-finite numbers are not valid JSON.")
