from __future__ import annotations

import json
import runpy
import traceback
from pathlib import Path


def run(request_path: str) -> None:
    import hou
    from PySide6 import QtCore, QtGui, QtWidgets

    request = json.loads(Path(request_path).read_text(encoding="utf-8"))
    result_path = Path(request["result_path"])
    try:
        kind = request["kind"]
        if kind == "viewport":
            module_path = Path(__file__).with_name("viewport.py")
        elif kind == "window":
            module_path = Path(__file__).with_name("window.py")
        else:
            raise RuntimeError("Unsupported screenshot kind: " + str(kind))
        runtime = runpy.run_path(str(module_path))
        runtime["capture"](request, hou, QtCore, QtGui, QtWidgets)
        payload = {"ok": True}
    except BaseException as exc:
        payload = {
            "ok": False,
            "message": str(exc) or type(exc).__name__,
            "detail": traceback.format_exc(),
        }
    result_path.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
