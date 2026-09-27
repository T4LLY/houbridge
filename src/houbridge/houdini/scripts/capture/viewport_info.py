from __future__ import annotations

import json
import runpy
from pathlib import Path


def _runtime():
    return runpy.run_path(str(Path(__file__).with_name("runtime.py")))


def run(request_path: str) -> None:
    import hou

    request = json.loads(Path(request_path).read_text(encoding="utf-8"))
    output_path = Path(request["output_path"])
    runtime = _runtime()
    scenes = runtime["list_scene_viewers"](hou)
    if not scenes:
        payload = {"ok": False, "message": "No Scene Viewer pane is available."}
    else:
        payload = {
            "ok": True,
            **runtime["describe_scene_viewers"](scenes, hou),
        }
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
