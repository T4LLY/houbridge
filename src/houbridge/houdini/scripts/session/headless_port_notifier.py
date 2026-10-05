from __future__ import annotations

import json
import os
from pathlib import Path
import sys


_BOOTSTRAP_DIR = Path(os.environ["HOUBRIDGE_SESSION_BOOTSTRAP_DIR"])
_RESULT = _BOOTSTRAP_DIR / "bootstrap.result.json"


def _publish(payload: dict[str, object]) -> None:
    staging = _RESULT.with_name(_RESULT.name + ".tmp")
    staging.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    os.replace(staging, _RESULT)


def main() -> int:
    if len(sys.argv) != 3:
        raise RuntimeError("headless port notifier expects Houdini PID and port")

    raw_pid, raw_port = sys.argv[1:]
    if not raw_pid.isdigit() or int(raw_pid) <= 0:
        raise RuntimeError(f"invalid Houdini PID: {raw_pid!r}")
    if not raw_port.isdigit() or not 1 <= int(raw_port) <= 65535:
        raise RuntimeError(f"invalid Houdini port: {raw_port!r}")

    _publish({"pid": int(raw_pid), "port": int(raw_port)})
    return 0


if __name__ == "__main__":
    try:
        exit_code = main()
    except BaseException as exc:
        raw_pid = sys.argv[1] if len(sys.argv) > 1 else ""
        error_pid = int(raw_pid) if raw_pid.isdigit() and int(raw_pid) > 0 else os.getpid()
        _publish(
            {
                "pid": error_pid,
                "port": None,
                "error": f"{type(exc).__name__}: {exc}",
            }
        )
        raise
    raise SystemExit(exit_code)
