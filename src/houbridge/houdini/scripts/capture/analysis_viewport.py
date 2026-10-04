from __future__ import annotations

import json
from pathlib import Path
import runpy
import traceback


def _runtime():
    return runpy.run_path(str(Path(__file__).with_name("runtime.py")))


def _analysis_runtime():
    return runpy.run_path(str(Path(__file__).with_name("analysis_runtime.py")))


def _view_types(hou):
    return {
        "top": hou.geometryViewportType.Top,
        "bottom": hou.geometryViewportType.Bottom,
        "front": hou.geometryViewportType.Front,
        "back": hou.geometryViewportType.Back,
        "left": hou.geometryViewportType.Left,
        "right": hou.geometryViewportType.Right,
        "persp": hou.geometryViewportType.Perspective,
        "uv": hou.geometryViewportType.UV,
    }


def _write_result(path: Path, payload: dict[str, object]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )


def _run(request: dict[str, object], hou, QtWidgets) -> dict[str, object]:
    runtime = _runtime()
    analysis_runtime = _analysis_runtime()
    error_type = runtime["CaptureRequestError"]
    resolve_scene_viewer = runtime["resolve_scene_viewer"]
    clone_scene_viewer = runtime["clone_scene_viewer"]
    close_scene_viewer = runtime["close_scene_viewer"]
    process_events = runtime["process_events"]
    constrained_size = runtime["constrained_size"]
    install_dso = analysis_runtime["install_dso"]
    resolve_models = analysis_runtime["resolve_models"]
    flipbook_analysis = analysis_runtime["flipbook_analysis"]

    analysis = request["analysis"]
    capture_pass = str(analysis["pass"])
    if capture_pass not in {"depth", "grid", "normal"}:
        raise error_type(
            "capture_analysis_pass_unavailable",
            f"Capture pass {capture_pass!r} is not implemented yet.",
        )
    model_paths = resolve_models(tuple(analysis["model_paths"]), hou, error_type)
    grid_unit = analysis.get("unit")
    png_paths = [Path(value) for value in request["png_paths"]]
    trigger_paths = [Path(value) for value in request["trigger_paths"]]
    requested_views = list(request["requested_views"])
    if len(png_paths) != len(trigger_paths):
        raise RuntimeError("Analysis capture output/trigger count mismatch.")

    install_dso(Path(str(request["dso_path"])))
    generation = str(request["generation"])
    scale = float(request["scale"])
    max_width = int(request["max_width"])
    max_height = int(request["max_height"])
    source_scene = resolve_scene_viewer(hou, request.get("pane"))
    view_types = _view_types(hou)

    def capture(scene, viewport, index):
        _x, _y, width, height = viewport.geometry()
        resolution = constrained_size(width, height, scale, max_width, max_height)
        flipbook_analysis(
            scene,
            viewport,
            output_path=png_paths[index],
            trigger_path=trigger_paths[index],
            generation=generation,
            capture_pass=capture_pass,
            model_paths=model_paths,
            grid_unit=grid_unit,
            resolution=resolution,
            crop_camera=False,
            hou=hou,
        )

    if not requested_views:
        capture(source_scene, source_scene.curViewport(), 0)
        return {"ok": True}

    scene = clone_scene_viewer(source_scene, hou, QtWidgets)
    try:
        scene.setViewportLayout(hou.geometryViewportLayout.Single)
        process_events(hou, QtWidgets)
        viewport = scene.curViewport()
        for index, view_name in enumerate(requested_views):
            viewport.changeType(view_types[view_name])
            process_events(hou, QtWidgets)
            viewport.frameAll()
            process_events(hou, QtWidgets)
            capture(scene, viewport, index)
    finally:
        close_scene_viewer(scene)
    return {"ok": True}


def run(request_path: str) -> None:
    import hou
    from PySide6 import QtWidgets

    request = json.loads(Path(request_path).read_text(encoding="utf-8"))
    result_path = Path(str(request["result_path"]))
    try:
        payload = _run(request, hou, QtWidgets)
    except BaseException as exc:
        payload = {
            "ok": False,
            "message": str(exc) or type(exc).__name__,
            "detail": traceback.format_exc(),
        }
        code = getattr(exc, "code", None)
        context = getattr(exc, "context", None)
        if isinstance(code, str) and code:
            payload["code"] = code
        if isinstance(context, dict) and context:
            payload["context"] = context
    _write_result(result_path, payload)
