from __future__ import annotations

import json
import runpy
import traceback
from pathlib import Path



def _runtime():
    return runpy.run_path(str(Path(__file__).with_name("runtime.py")))


def _headless_runtime():
    return runpy.run_path(str(Path(__file__).with_name("headless_camera.py")))


def _node_type(hou, category, name):
    return hou.nodeType(category, name)


def _obj_camera_type(hou):
    return _node_type(hou, hou.objNodeTypeCategory(), "cam")


def _sop_camera_type(hou):
    return _node_type(hou, hou.sopNodeTypeCategory(), "camera")


def _is_obj_camera(node, hou):
    camera_type = _obj_camera_type(hou)
    return camera_type is not None and node.type() == camera_type


def _is_sop_camera(node, hou):
    camera_type = _sop_camera_type(hou)
    return camera_type is not None and node.type() == camera_type


def _camera_prims(node, hou):
    geometry = node.geometry()
    if geometry is None:
        return ()
    return tuple(prim for prim in geometry.prims() if isinstance(prim, hou.CameraPrim))


def _obj_resolution(node):
    values = node.parmTuple("res").eval()
    return [int(values[0]), int(values[1])]


def _camera_resolution(camera):
    width, height = camera.resolution()
    return [int(width), int(height)]


def _camera_summary(path, camera_type, resolution):
    return {
        "path": path,
        "type": camera_type,
        "resolution": list(resolution),
    }


def list_cameras(hou):
    cameras = []
    obj_type = _obj_camera_type(hou)
    if obj_type is not None:
        for node in obj_type.instances():
            try:
                cameras.append(_camera_summary(node.path(), "obj", _obj_resolution(node)))
            except BaseException:
                continue

    sop_type = _sop_camera_type(hou)
    if sop_type is not None:
        for node in sop_type.instances():
            try:
                for prim in _camera_prims(node, hou):
                    cameras.append(
                        _camera_summary(
                            f"{node.path()}:{prim.number()}",
                            "sop",
                            _camera_resolution(prim.camera()),
                        )
                    )
            except BaseException:
                continue
    cameras.sort(key=lambda item: item["path"])
    return cameras


def _split_camera_path(camera_path, runtime):
    error = runtime["CaptureRequestError"]
    if not isinstance(camera_path, str) or not camera_path.startswith("/"):
        raise error("camera_path_invalid", "Camera path must be an absolute Houdini node path.")
    if camera_path.count(":") > 1:
        raise error(
            "camera_unsupported",
            "Initial camera capture supports OBJ Camera paths and first-output SOP Camera paths only.",
        )
    if ":" not in camera_path:
        return camera_path, None
    node_path, selector = camera_path.rsplit(":", 1)
    if not node_path or not selector:
        raise error("camera_path_invalid", f"Camera path {camera_path!r} is invalid.")
    return node_path, selector


def _prim_name(prim):
    try:
        value = prim.attribValue("name")
    except BaseException:
        return None
    return value if isinstance(value, str) and value else None


def _select_sop_camera(node, selector, hou, runtime):
    error = runtime["CaptureRequestError"]
    prims = _camera_prims(node, hou)
    if selector is None:
        if len(prims) == 1:
            return prims[0]
        if not prims:
            raise error("camera_invalid", f"SOP node {node.path()!r} does not contain a camera primitive.")
        raise error(
            "camera_ambiguous",
            f"SOP node {node.path()!r} contains multiple camera primitives; specify one by name or primitive number.",
            context={
                "cameras": [
                    _camera_summary(
                        f"{node.path()}:{prim.number()}",
                        "sop",
                        _camera_resolution(prim.camera()),
                    )
                    for prim in prims
                ]
            },
        )

    if selector.isdigit():
        number = int(selector)
        for prim in prims:
            if prim.number() == number:
                return prim
    else:
        matches = tuple(prim for prim in prims if _prim_name(prim) == selector)
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise error(
                "camera_ambiguous",
                f"SOP camera name {selector!r} is ambiguous in {node.path()!r}.",
                context={
                    "cameras": [
                        _camera_summary(
                            f"{node.path()}:{prim.number()}",
                            "sop",
                            _camera_resolution(prim.camera()),
                        )
                        for prim in matches
                    ]
                },
            )
    raise error(
        "camera_not_found",
        f"SOP camera {node.path()}:{selector} was not found.",
    )


def resolve_camera(camera_path, hou, runtime):
    error = runtime["CaptureRequestError"]
    node_path, selector = _split_camera_path(camera_path, runtime)
    node = hou.node(node_path)
    if node is None:
        raise error("camera_not_found", f"Camera node {node_path!r} was not found.")

    if _is_obj_camera(node, hou):
        if selector is not None:
            raise error("camera_invalid", "OBJ Camera paths do not accept a primitive selector.")
        return {
            "path": node.path(),
            "type": "obj",
            "node": node,
            "prim": None,
            "viewport_selector": None,
        }

    if _is_sop_camera(node, hou):
        prim = _select_sop_camera(node, selector, hou, runtime)
        return {
            "path": f"{node.path()}:{prim.number()}",
            "type": "sop",
            "node": node,
            "prim": prim,
            "viewport_selector": str(prim.number()),
        }

    raise error(
        "camera_unsupported",
        "Initial camera capture supports OBJ Camera and SOP Camera only.",
    )


def _obj_detail(resolved):
    node = resolved["node"]
    return {
        "path": resolved["path"],
        "type": "obj",
        "resolution": _obj_resolution(node),
        "projection": node.parm("projection").evalAsString(),
        "focal_length": float(node.evalParm("focal")),
        "aperture": float(node.evalParm("aperture")),
        "pixel_aspect": float(node.evalParm("aspect")),
        "near_clip": float(node.evalParm("near")),
        "far_clip": float(node.evalParm("far")),
        "focus_distance": float(node.evalParm("focus")),
        "f_stop": float(node.evalParm("fstop")),
    }


def _sop_detail(resolved):
    camera = resolved["prim"].camera()
    return {
        "path": resolved["path"],
        "type": "sop",
        "resolution": _camera_resolution(camera),
        "projection": camera.projectionToken(),
        "focal_length": float(camera.focal()),
        "aperture": float(camera.aperture()),
        "pixel_aspect": float(camera.pixelAspect()),
        "near_clip": float(camera.nearClippingPlane()),
        "far_clip": float(camera.farClippingPlane()),
        "focus_distance": float(camera.focusDistance()),
        "f_stop": float(camera.fstop()),
    }


def describe_camera(resolved):
    if resolved["type"] == "obj":
        return _obj_detail(resolved)
    return _sop_detail(resolved)


def _capture_camera_gui(request, resolved, hou, runtime):
    from PySide6 import QtCore, QtGui, QtWidgets

    resolve_scene_viewer = runtime["resolve_scene_viewer"]
    clone_scene_viewer = runtime["clone_scene_viewer"]
    close_scene_viewer = runtime["close_scene_viewer"]
    process_events = runtime["process_events"]
    flipbook_png = runtime["flipbook_png"]
    constrained_size = runtime["constrained_size"]

    source_scene = resolve_scene_viewer(hou, request.get("pane"))
    scene = clone_scene_viewer(source_scene, hou, QtWidgets)
    try:
        scene.setViewportLayout(hou.geometryViewportLayout.Single)
        process_events(hou, QtWidgets)
        viewport = scene.curViewport()
        if resolved["type"] == "obj":
            viewport.setCamera(resolved["node"])
            resolution = _obj_resolution(resolved["node"])
        else:
            viewport.setCamera(resolved["node"], resolved["viewport_selector"])
            resolution = _camera_resolution(resolved["prim"].camera())
        process_events(hou, QtWidgets)
        output_resolution = constrained_size(
            int(resolution[0]),
            int(resolution[1]),
            float(request["scale"]),
            int(request["max_width"]),
            int(request["max_height"]),
        )
        flipbook_resolution = output_resolution
        output_scale = 1.0
        if min(output_resolution) < 2:
            flipbook_resolution = tuple(value * 2 for value in output_resolution)
            output_scale = 0.5
        flipbook_png(
            scene,
            viewport,
            Path(request["png_path"]),
            scale=output_scale,
            max_width=int(request["max_width"]),
            max_height=int(request["max_height"]),
            flipbook_resolution=flipbook_resolution,
            crop_camera=True,
            hou=hou,
            QtCore=QtCore,
            QtGui=QtGui,
        )
    finally:
        close_scene_viewer(scene)


def _capture_camera_headless(request, resolved, hou, runtime):
    if request.get("pane") is not None:
        raise runtime["CaptureRequestError"](
            "viewport_unavailable",
            "--pane is unavailable for headless camera capture.",
        )

    constrained_size = runtime["constrained_size"]
    headless = _headless_runtime()
    if resolved["type"] == "obj":
        resolution = _obj_resolution(resolved["node"])
    else:
        resolution = _camera_resolution(resolved["prim"].camera())
    output_resolution = constrained_size(
        int(resolution[0]),
        int(resolution[1]),
        float(request["scale"]),
        int(request["max_width"]),
        int(request["max_height"]),
    )
    rop = headless["create_flipbook_rop"](
        hou,
        camera_path=resolved["path"],
        resolution=output_resolution,
    )
    try:
        headless["render_flipbook_rop"](rop, Path(request["png_path"]), hou)
    finally:
        headless["destroy_flipbook_rop"](rop)


def capture_camera(request, resolved, hou, runtime):
    if hou.isUIAvailable():
        _capture_camera_gui(request, resolved, hou, runtime)
    else:
        _capture_camera_headless(request, resolved, hou, runtime)


def run(request_path: str) -> None:
    import hou

    request = json.loads(Path(request_path).read_text(encoding="utf-8"))
    result_path = Path(request["result_path"])
    runtime = _runtime()
    try:
        mode = request["mode"]
        if mode == "list":
            payload = {"ok": True, "cameras": list_cameras(hou)}
        else:
            resolved = resolve_camera(request["camera_path"], hou, runtime)
            if mode == "detail":
                payload = {"ok": True, "camera": describe_camera(resolved)}
            elif mode == "capture":
                capture_camera(request, resolved, hou, runtime)
                payload = {"ok": True}
            else:
                raise RuntimeError(f"Unsupported camera mode: {mode!r}")
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
    result_path.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
