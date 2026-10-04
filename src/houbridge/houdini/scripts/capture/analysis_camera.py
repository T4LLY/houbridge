from __future__ import annotations

import json
from pathlib import Path
import runpy
import traceback


def _runtime():
    return runpy.run_path(str(Path(__file__).with_name("runtime.py")))


def _analysis_runtime():
    return runpy.run_path(str(Path(__file__).with_name("analysis_runtime.py")))


def _camera_runtime():
    return runpy.run_path(str(Path(__file__).with_name("camera.py")))


def _write_result(path: Path, payload: dict[str, object]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )


def _resolution(resolved, camera_runtime):
    if resolved["type"] == "obj":
        return camera_runtime["_obj_resolution"](resolved["node"])
    return camera_runtime["_camera_resolution"](resolved["prim"].camera())


def _run(request: dict[str, object], hou, QtWidgets) -> dict[str, object]:
    runtime = _runtime()
    analysis_runtime = _analysis_runtime()
    camera_runtime = _camera_runtime()
    error_type = runtime["CaptureRequestError"]
    resolve_scene_viewer = runtime["resolve_scene_viewer"]
    clone_scene_viewer = runtime["clone_scene_viewer"]
    close_scene_viewer = runtime["close_scene_viewer"]
    process_events = runtime["process_events"]
    constrained_size = runtime["constrained_size"]
    install_dso = analysis_runtime["install_dso"]
    resolve_models = analysis_runtime["resolve_models"]
    flipbook_analysis = analysis_runtime["flipbook_analysis"]
    resolve_camera = camera_runtime["resolve_camera"]

    analysis = request["analysis"]
    capture_pass = str(analysis["pass"])
    if capture_pass not in {"depth", "grid"}:
        raise error_type(
            "capture_analysis_pass_unavailable",
            f"Capture pass {capture_pass!r} is not implemented yet.",
        )
    model_paths = resolve_models(tuple(analysis["model_paths"]), hou, error_type)
    grid_unit = analysis.get("unit")
    resolved = resolve_camera(str(request["camera_path"]), hou, runtime)

    install_dso(Path(str(request["dso_path"])))
    source_scene = resolve_scene_viewer(hou, request.get("pane"))
    scene = clone_scene_viewer(source_scene, hou, QtWidgets)
    try:
        scene.setViewportLayout(hou.geometryViewportLayout.Single)
        process_events(hou, QtWidgets)
        viewport = scene.curViewport()
        if resolved["type"] == "obj":
            viewport.setCamera(resolved["node"])
        else:
            viewport.setCamera(resolved["node"], resolved["viewport_selector"])
        process_events(hou, QtWidgets)

        source_resolution = _resolution(resolved, camera_runtime)
        output_resolution = constrained_size(
            int(source_resolution[0]),
            int(source_resolution[1]),
            float(request["scale"]),
            int(request["max_width"]),
            int(request["max_height"]),
        )
        flipbook_analysis(
            scene,
            viewport,
            output_path=Path(str(request["png_path"])),
            trigger_path=Path(str(request["trigger_path"])),
            generation=str(request["generation"]),
            capture_pass=capture_pass,
            model_paths=model_paths,
            grid_unit=grid_unit,
            resolution=output_resolution,
            crop_camera=True,
            hou=hou,
        )
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
