from __future__ import annotations

import contextlib
import json
import os
import reprlib
import runpy
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
    source_import_root = request.get("source_import_root")
    source_argv = request["argv"]

    stdout_path = Path(request["stdout_file"])
    stderr_path = Path(request["stderr_file"])
    traceback_path = Path(request["traceback_file"])
    result_json_path = Path(request["result_json_file"])
    result_text_path = Path(request["result_text_file"])
    status_path = Path(request["status_file"])

    history_runtime = None
    history_context = None
    history_request = request.get("history")
    if history_request is not None:
        if not isinstance(history_request, dict):
            raise RuntimeError("Execution History request must be a JSON object.")
        runtime_script = history_request.get("runtime_script")
        request_file = history_request.get("request_file")
        if not isinstance(runtime_script, str) or not runtime_script:
            raise RuntimeError("Execution History runtime script is missing.")
        if not isinstance(request_file, str) or not request_file:
            raise RuntimeError("Execution History request file is missing.")
        history_runtime = runpy.run_path(runtime_script)
        history_context = history_runtime["prepare"](request_file)

    try:
        status: dict[str, object] = {"python_ok": False, "result_kind": None}
        namespace = {
            "__name__": "__main__",
            # Preserve the useful native-Houdini execution convenience from the
            # previous runtime without importing any History behavior.
            "hou": hou,
        }
        compile_filename = "<houbridge --code>"
        if source_path is not None:
            namespace["__file__"] = source_path
            compile_filename = source_path

        with (
            stdout_path.open("w", encoding="utf-8", newline="") as stdout_file,
            stderr_path.open("w", encoding="utf-8", newline="") as stderr_file,
        ):
            previous_argv = sys.argv
            previous_sys_path = list(sys.path)
            try:
                sys.argv = list(source_argv)
                if source_import_root is not None:
                    if (
                        not isinstance(source_import_root, str)
                        or not source_import_root
                    ):
                        raise RuntimeError("Execution source import root is invalid.")
                    sys.path.insert(0, source_import_root)
                with (
                    contextlib.redirect_stdout(stdout_file),
                    contextlib.redirect_stderr(stderr_file),
                ):
                    exec(
                        compile(source, compile_filename, "exec"), namespace, namespace
                    )
            except BaseException:
                with traceback_path.open(
                    "w", encoding="utf-8", newline=""
                ) as traceback_file:
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
                sys.path[:] = previous_sys_path

        # Publish the caller Python outcome before best-effort History finalization.
        # The host can then distinguish a terminal caller outcome from a transport
        # timeout caused only by post-Python History bookkeeping.
        _atomic_write_json(status_path, status)

        if history_runtime is not None and history_context is not None:
            try:
                history_runtime["finalize"](history_context)
            except Exception:
                # Caller Python has already reached a terminal outcome. History is
                # best-effort after start and must not redefine that outcome.
                pass
    finally:
        if history_runtime is not None and history_context is not None:
            try:
                history_runtime["close"](history_context)
            except Exception:
                # Recorder cleanup is post-start best-effort and must not mask
                # an artifact failure or redefine the caller outcome.
                pass


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
