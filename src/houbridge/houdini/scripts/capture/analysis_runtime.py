from __future__ import annotations

import ctypes
import os
from pathlib import Path
import sys
import uuid


def install_dso(path: Path) -> None:
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


def resolve_models(paths, hou, error_type):
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


def flipbook_analysis(
    scene,
    viewport,
    *,
    output_path: Path,
    trigger_path: Path,
    generation: str,
    capture_pass: str,
    model_paths: tuple[str, ...],
    grid_unit,
    curvature_scale: float,
    curvature_colormap: str,
    resolution: tuple[int, int],
    crop_camera: bool,
    hou,
) -> None:
    settings = scene.flipbookSettings().stash()
    frame = hou.frame()
    settings.frameRange((frame, frame))
    settings.outputToMPlay(False)
    settings.output(str(trigger_path))
    settings.useResolution(True)
    settings.resolution(tuple(int(value) for value in resolution))
    settings.outputZoom(100)
    if crop_camera:
        settings.cropOutMaskOverlay(True)
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
    if capture_pass == "curvature":
        values["HOUBRIDGE_CAPTURE_CURVATURE_SCALE"] = format(float(curvature_scale), ".17g")
        values["HOUBRIDGE_CAPTURE_CURVATURE_COLORMAP"] = curvature_colormap
    previous = _set_environment(values)
    try:
        scene.flipbook(viewport, settings)
    finally:
        _restore_environment(previous)
        trigger_path.unlink(missing_ok=True)
    if not output_path.is_file():
        raise RuntimeError("Native analysis SceneHook did not produce the requested PNG.")
