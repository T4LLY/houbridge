from __future__ import annotations

import ctypes
import json
import os
from pathlib import Path
import runpy
import sys
import traceback
import uuid


def _runtime():
    return runpy.run_path(str(Path(__file__).with_name("runtime.py")))


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


def _install_dso(path: Path) -> None:
    library = ctypes.CDLL(str(path))
    install = library.houbridgeInstallCaptureSceneHookGate
    install.argtypes = []
    install.restype = ctypes.c_int
    if install() != 1:
        raise RuntimeError("Native Capture SceneHook registration failed.")
    keepalive = getattr(sys, "_houbridge_capture_native_dsos", None)
    if keepalive is None:
        keepalive = []
        setattr(sys, "_houbridge_capture_native_dsos", keepalive)
    keepalive.append(library)


def _resolve_models(paths, hou, error_type):
    resolved = []
    for path in paths:
        node = hou.node(path)
        if node is None:
            raise error_type(
                "capture_model_not_found",
                f"Model node was not found: {path}",
            )
        if node.type().category() != hou.objNodeTypeCategory():
            raise error_type(
                "capture_model_invalid",
                f"Model path must identify an OBJ node: {path}",
            )
        resolved.append(node.path())
    return tuple(resolved)


def _set_environment(values: dict[str, str]):
    previous = {key: os.environ.get(key) for key in values}
    os.environ.update(values)
    return previous


def _restore_environment(previous: dict[str, str | None]) -> None:
    for key, value in previous.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def _flipbook_analysis(
    scene,
    viewport,
    *,
    output_path: Path,
    trigger_path: Path,
    generation: str,
    capture_pass: str,
    model_paths: tuple[str, ...],
    grid_unit,
    scale: float,
    max_width: int,
    max_height: int,
    hou,
    constrained_size,
) -> None:
    _x, _y, width, height = viewport.geometry()
    final_size = constrained_size(width, height, scale, max_width, max_height)
    settings = scene.flipbookSettings().stash()
    frame = hou.frame()
    settings.frameRange((frame, frame))
    settings.outputToMPlay(False)
    settings.output(str(trigger_path))
    settings.useResolution(True)
    settings.resolution(final_size)
    settings.outputZoom(100)
    request_id = uuid.uuid4().hex
    values = {
        "HOUBRIDGE_CAPTURE_GENERATION": generation,
        "HOUBRIDGE_CAPTURE_ANALYSIS_REQUEST": request_id,
        "HOUBRIDGE_CAPTURE_ANALYSIS_PASS": capture_pass,
        "HOUBRIDGE_CAPTURE_ANALYSIS_OUTPUT": str(output_path),
        "HOUBRIDGE_CAPTURE_ANALYSIS_MODELS": ";".join(model_paths),
    }
    if grid_unit is not None:
        values["HOUBRIDGE_CAPTURE_ANALYSIS_UNIT"] = format(float(grid_unit), ".17g")
    previous = _set_environment(values)
    try:
        scene.flipbook(viewport, settings)
    finally:
        _restore_environment(previous)
        trigger_path.unlink(missing_ok=True)
    if not output_path.is_file():
        raise RuntimeError("Native analysis SceneHook did not produce the requested PNG.")


def _run(request: dict[str, object], hou, QtWidgets) -> dict[str, object]:
    runtime = _runtime()
    error_type = runtime["CaptureRequestError"]
    resolve_scene_viewer = runtime["resolve_scene_viewer"]
    clone_scene_viewer = runtime["clone_scene_viewer"]
    close_scene_viewer = runtime["close_scene_viewer"]
    process_events = runtime["process_events"]
    constrained_size = runtime["constrained_size"]

    analysis = request["analysis"]
    capture_pass = str(analysis["pass"])
    if capture_pass not in {"depth", "grid"}:
        raise error_type(
            "capture_analysis_pass_unavailable",
            f"Capture pass {capture_pass!r} is not implemented yet.",
        )
    model_paths = _resolve_models(tuple(analysis["model_paths"]), hou, error_type)
    grid_unit = analysis.get("unit")
    png_paths = [Path(value) for value in request["png_paths"]]
    trigger_paths = [Path(value) for value in request["trigger_paths"]]
    requested_views = list(request["requested_views"])
    if len(png_paths) != len(trigger_paths):
        raise RuntimeError("Analysis capture output/trigger count mismatch.")

    _install_dso(Path(str(request["dso_path"])))
    generation = str(request["generation"])
    scale = float(request["scale"])
    max_width = int(request["max_width"])
    max_height = int(request["max_height"])
    source_scene = resolve_scene_viewer(hou, request.get("pane"))
    view_types = _view_types(hou)

    if not requested_views:
        _flipbook_analysis(
            source_scene,
            source_scene.curViewport(),
            output_path=png_paths[0],
            trigger_path=trigger_paths[0],
            generation=generation,
            capture_pass=capture_pass,
            model_paths=model_paths,
            grid_unit=grid_unit,
            scale=scale,
            max_width=max_width,
            max_height=max_height,
            hou=hou,
            constrained_size=constrained_size,
        )
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
            _flipbook_analysis(
                scene,
                viewport,
                output_path=png_paths[index],
                trigger_path=trigger_paths[index],
                generation=generation,
                capture_pass=capture_pass,
                model_paths=model_paths,
                grid_unit=grid_unit,
                scale=scale,
                max_width=max_width,
                max_height=max_height,
                hou=hou,
                constrained_size=constrained_size,
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
