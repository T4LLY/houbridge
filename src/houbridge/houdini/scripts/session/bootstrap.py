from __future__ import annotations

import json
import os
from pathlib import Path

import hou


_SCRIPT = Path(__file__)
_REQUEST = _SCRIPT.with_name("bootstrap.request.json")
_RESULT = _SCRIPT.with_name("bootstrap.result.json")
_HEADLESS_STDIN_HOLD: int | None = None


def _publish(payload: dict[str, object]) -> None:
    staging = _RESULT.with_name(_RESULT.name + ".tmp")
    staging.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    os.replace(staging, _RESULT)


def _selected_port() -> int:
    output, errors = hou.hscript("openport -a -q")
    if errors.strip():
        raise RuntimeError(errors.strip())
    value = output.strip()
    if not value.isdigit():
        raise RuntimeError(f"openport -a returned an invalid port: {value!r}")
    port = int(value)
    if not 1 <= port <= 65535:
        raise RuntimeError(f"openport -a returned an invalid port: {port}")
    return port


def _prepare_headless_console_wait() -> None:
    global _HEADLESS_STDIN_HOLD
    read_fd, write_fd = os.pipe()
    try:
        os.dup2(read_fd, 0)
    finally:
        os.close(read_fd)
    # Keep one writer open in this process so ``hython -b -i`` waits for input
    # without consuming the user's console and without seeing EOF after Houbridge exits.
    _HEADLESS_STDIN_HOLD = write_fd


def main() -> None:
    pid = os.getpid()
    _publish({"pid": pid, "port": None})
    try:
        request = json.loads(_REQUEST.read_text(encoding="utf-8"))
        hip_file = request.get("file")
        headless = request.get("headless")
        if hip_file is not None:
            if not isinstance(hip_file, str) or not hip_file:
                raise RuntimeError("bootstrap file request is invalid")
            hou.hipFile.load(hip_file)
        if not isinstance(headless, bool):
            raise RuntimeError("bootstrap headless request is invalid")
        if headless:
            _prepare_headless_console_wait()

        port = _selected_port()
        _publish({"pid": pid, "port": port})
    except BaseException as exc:
        _publish({"pid": pid, "port": None, "error": f"{type(exc).__name__}: {exc}"})
        raise


if __name__ == "__main__":
    main()
