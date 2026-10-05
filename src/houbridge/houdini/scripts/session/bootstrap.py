from __future__ import annotations

import json
import os
from pathlib import Path


_BOOTSTRAP_DIR_ENV = "HOUBRIDGE_SESSION_BOOTSTRAP_DIR"
_BOOTSTRAP_DIR = Path(os.environ[_BOOTSTRAP_DIR_ENV])
_REQUEST = _BOOTSTRAP_DIR / "bootstrap.request.json"
_RESULT = _BOOTSTRAP_DIR / "bootstrap.result.json"


def _publish(payload: dict[str, object]) -> None:
    staging = _RESULT.with_name(_RESULT.name + ".tmp")
    staging.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    os.replace(staging, _RESULT)


def _selected_port(hou: object) -> int:
    output, errors = hou.hscript("openport -a -q")  # type: ignore[attr-defined]
    if errors.strip():
        raise RuntimeError(errors.strip())
    value = output.strip()
    if not value.isdigit():
        raise RuntimeError(f"openport -a returned an invalid port: {value!r}")
    port = int(value)
    if not 1 <= port <= 65535:
        raise RuntimeError(f"openport -a returned an invalid port: {port}")
    return port


def main() -> None:
    pid = os.getpid()
    _publish({"pid": pid, "port": None})
    try:
        import hou

        request = json.loads(_REQUEST.read_text(encoding="utf-8"))
        hip_file = request.get("file")
        headless = request.get("headless")
        if hip_file is not None:
            if not isinstance(hip_file, str) or not hip_file:
                raise RuntimeError("bootstrap file request is invalid")
            hou.hipFile.load(hip_file)
        if not isinstance(headless, bool):
            raise RuntimeError("bootstrap headless request is invalid")
        port = _selected_port(hou)
        _publish({"pid": pid, "port": port})
    except BaseException as exc:
        _publish({"pid": pid, "port": None, "error": f"{type(exc).__name__}: {exc}"})
        raise


if __name__ == "__main__":
    main()
