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


def _headless_runtime():
    return runpy.run_path(str(Path(__file__).with_name("headless_camera.py")))


def _write_result(path: Path, payload: dict[str, object]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )


def _prepare(request, hou):
    runtime = _runtime()
    analysis_runtime = _analysis_runtime()
    camera_runtime = _camera_runtime()
    error_type = runtime["CaptureRequestError"]
    analysis = request["analysis"]
    capture_pass = str(analysis["pass"])
    if capture_pass not in {"depth", "grid", "normal", "object-id", "curvature"}:
        raise error_type(
            "capture_analysis_pass_unavailable",
            f"Capture pass {capture_pass!r} is not implemented yet.",
        )
    model_paths = analysis_runtime["resolve_models"](
        tuple(analysis["model_paths"]), hou, error_type
    )
    resolved = camera_runtime["resolve_camera"](str(request["camera_path"]), hou, runtime)
    if resolved["type"] == "obj":
        source_resolution = camera_runtime["_obj_resolution"](resolved["node"])
    else:
        source_resolution = camera_runtime["_camera_resolution"](resolved["prim"].camera())
    output_resolution = runtime["constrained_size"](
        int(source_resolution[0]),
        int(source_resolution[1]),
        float(request["scale"]),
        int(request["max_width"]),
        int(request["max_height"]),
    )
    return (
        runtime,
        analysis_runtime,
        resolved,
        model_paths,
        output_resolution,
        capture_pass,
        analysis.get("unit"),
        float(analysis.get("curvature_scale", 1.0)),
        str(analysis.get("curvature_colormap", "rg")),
    )


def _run_gui(request: dict[str, object], hou, QtWidgets) -> dict[str, object]:
    (
        runtime,
        analysis_runtime,
        resolved,
        model_paths,
        output_resolution,
        capture_pass,
        grid_unit,
        curvature_scale,
        curvature_colormap,
    ) = _prepare(request, hou)
    resolve_scene_viewer = runtime["resolve_scene_viewer"]
    clone_scene_viewer = runtime["clone_scene_viewer"]
    close_scene_viewer = runtime["close_scene_viewer"]
    process_events = runtime["process_events"]
    flipbook_analysis = analysis_runtime["flipbook_analysis"]
    camera_flipbook_resolution_plan = analysis_runtime["camera_flipbook_resolution_plan"]
    resize_png_to_resolution = analysis_runtime["resize_png_to_resolution"]

    analysis_runtime["install_dso"](Path(str(request["dso_path"])))
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

        flipbook_resolution, output_scale = camera_flipbook_resolution_plan(output_resolution)
        output_path = Path(str(request["png_path"]))
        flipbook_analysis(
            scene,
            viewport,
            output_path=output_path,
            trigger_path=Path(str(request["trigger_path"])),
            generation=str(request["generation"]),
            capture_pass=capture_pass,
            model_paths=model_paths,
            grid_unit=grid_unit,
            curvature_scale=curvature_scale,
            curvature_colormap=curvature_colormap,
            resolution=flipbook_resolution,
            crop_camera=True,
            hou=hou,
        )
        if output_scale != 1.0:
            resize_png_to_resolution(output_path, output_resolution)
    finally:
        close_scene_viewer(scene)
    return {"ok": True}


def _run_headless(request: dict[str, object], hou) -> dict[str, object]:
    (
        runtime,
        analysis_runtime,
        resolved,
        model_paths,
        output_resolution,
        capture_pass,
        grid_unit,
        curvature_scale,
        curvature_colormap,
    ) = _prepare(request, hou)
    if request.get("pane") is not None:
        raise runtime["CaptureRequestError"](
            "viewport_unavailable",
            "--pane is unavailable for headless camera capture.",
        )

    analysis_runtime["install_dso"](Path(str(request["dso_path"])))
    headless = _headless_runtime()
    rop = headless["create_flipbook_rop"](
        hou,
        camera_path=resolved["path"],
        resolution=output_resolution,
    )
    try:
        analysis_runtime["flipbook_analysis_rop"](
            rop,
            output_path=Path(str(request["png_path"])),
            trigger_path=Path(str(request["trigger_path"])),
            generation=str(request["generation"]),
            capture_pass=capture_pass,
            model_paths=model_paths,
            grid_unit=grid_unit,
            curvature_scale=curvature_scale,
            curvature_colormap=curvature_colormap,
            hou=hou,
        )
    finally:
        headless["destroy_flipbook_rop"](rop)
    return {"ok": True}


def _run(request: dict[str, object], hou, QtWidgets=None) -> dict[str, object]:
    if hou.isUIAvailable():
        if QtWidgets is None:
            from PySide6 import QtWidgets as imported_qt_widgets

            QtWidgets = imported_qt_widgets
        return _run_gui(request, hou, QtWidgets)
    return _run_headless(request, hou)


def run(request_path: str) -> None:
    import hou

    request = json.loads(Path(request_path).read_text(encoding="utf-8"))
    result_path = Path(str(request["result_path"]))
    try:
        payload = _run(request, hou)
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
