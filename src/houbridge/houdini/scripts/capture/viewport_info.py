from __future__ import annotations

import json
from pathlib import Path


def run(request_path: str) -> None:
    import hou

    request = json.loads(Path(request_path).read_text(encoding="utf-8"))
    output_path = Path(request["output_path"])
    scene = hou.ui.curDesktop().paneTabOfType(hou.paneTabType.SceneViewer)
    if scene is None:
        payload = {"ok": False, "message": "No Scene Viewer pane is available."}
    else:
        view_names = {
            hou.geometryViewportType.Top: "top",
            hou.geometryViewportType.Bottom: "bottom",
            hou.geometryViewportType.Front: "front",
            hou.geometryViewportType.Back: "back",
            hou.geometryViewportType.Left: "left",
            hou.geometryViewportType.Right: "right",
            hou.geometryViewportType.Perspective: "persp",
            hou.geometryViewportType.UV: "uv",
        }
        entries = []
        for viewport in scene.viewports():
            if not viewport.isVisible():
                continue
            _x, _y, width, height = viewport.geometry()
            entries.append(
                {
                    "name": viewport.name(),
                    "type": view_names.get(
                        viewport.type(),
                        str(viewport.type()).rsplit(".", 1)[-1].lower(),
                    ),
                    "width": int(width),
                    "height": int(height),
                }
            )
        payload = {"ok": True, "viewports": entries}
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
