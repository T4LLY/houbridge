from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from houbridge.houdini.scripts.capture import analysis_camera


class _Viewport:
    def __init__(self) -> None:
        self.camera_calls = []
        self.frame_all_calls = 0

    def setCamera(self, *args) -> None:
        self.camera_calls.append(args)

    def frameAll(self) -> None:
        self.frame_all_calls += 1


class _Scene:
    def __init__(self, viewport: _Viewport) -> None:
        self.viewport = viewport
        self.layouts = []

    def setViewportLayout(self, layout) -> None:
        self.layouts.append(layout)

    def curViewport(self):
        return self.viewport


class _Node:
    pass


class _Prim:
    def camera(self):
        return SimpleNamespace(resolution=lambda: (1280, 720))


def _run_camera(
    monkeypatch,
    *,
    resolved,
    camera_path: str,
    capture_pass: str = "depth",
    curvature_scale: float = 1.0,
    curvature_colormap: str = "rg",
    scale: float = 0.5,
):
    viewport = _Viewport()
    scene = _Scene(viewport)
    source_scene = object()
    flipbook_calls = []
    closed = []
    processed = []
    obj_resolution_calls = []

    class _CaptureRequestError(RuntimeError):
        def __init__(self, code, message, context=None):
            super().__init__(message)
            self.code = code
            self.context = context

    runtime = {
        "CaptureRequestError": _CaptureRequestError,
        "resolve_scene_viewer": lambda _hou, pane: source_scene if pane == "panetab4" else None,
        "clone_scene_viewer": lambda source, _hou, _widgets: scene if source is source_scene else None,
        "close_scene_viewer": lambda value: closed.append(value),
        "process_events": lambda _hou, _widgets: processed.append(True),
        "constrained_size": lambda width, height, scale, max_width, max_height: (
            max(1, int(round(width * scale * min(1.0, max_width / (width * scale), max_height / (height * scale))))),
            max(1, int(round(height * scale * min(1.0, max_width / (width * scale), max_height / (height * scale))))),
        ),
    }
    analysis_runtime = {
        "install_dso": lambda path: None,
        "resolve_models": lambda paths, _hou, _error: tuple(paths),
        "flipbook_analysis": lambda *args, **kwargs: flipbook_calls.append((args, kwargs)),
        "camera_flipbook_resolution_plan": lambda resolution: (
            (tuple(value * 2 for value in resolution), 0.5)
            if min(resolution) < 2
            else (tuple(resolution), 1.0)
        ),
        "resize_png_to_resolution": lambda path, resolution: flipbook_calls.append(
            ("resize", (path, resolution))
        ),
    }
    camera_runtime = {
        "resolve_camera": lambda path, _hou, _runtime: resolved if path == camera_path else None,
        "_obj_resolution": lambda node: obj_resolution_calls.append(node) or [1920, 1080],
        "_camera_resolution": lambda camera: list(camera.resolution()),
    }
    monkeypatch.setattr(analysis_camera, "_runtime", lambda: runtime)
    monkeypatch.setattr(analysis_camera, "_analysis_runtime", lambda: analysis_runtime)
    monkeypatch.setattr(analysis_camera, "_camera_runtime", lambda: camera_runtime)

    hou = SimpleNamespace(geometryViewportLayout=SimpleNamespace(Single="single"), isUIAvailable=lambda: True)
    request = {
        "analysis": {
            "pass": capture_pass,
            "model_paths": ["/obj/a"],
            "unit": None,
            "curvature_scale": curvature_scale,
            "curvature_colormap": curvature_colormap,
        },
        "dso_path": "D:/cache/capture.dll",
        "generation": "abc123",
        "camera_path": camera_path,
        "png_path": "D:/Temp/camera.png",
        "trigger_path": "D:/Temp/trigger.png",
        "scale": scale,
        "max_width": 800,
        "max_height": 600,
        "pane": "panetab4",
    }

    result = analysis_camera._run(request, hou, object())
    return result, viewport, scene, flipbook_calls, closed, processed, obj_resolution_calls


def test_analysis_camera_preserves_obj_camera_composition_and_resolution(monkeypatch) -> None:
    node = _Node()
    resolved = {
        "type": "obj",
        "node": node,
        "prim": None,
        "viewport_selector": None,
    }

    result, viewport, scene, calls, closed, processed, resolution_calls = _run_camera(
        monkeypatch,
        resolved=resolved,
        camera_path="/obj/cam1",
    )

    assert result == {"ok": True}
    assert viewport.camera_calls == [(node,)]
    assert viewport.frame_all_calls == 0
    assert scene.layouts == ["single"]
    assert resolution_calls == [node]
    assert calls[0][1]["resolution"] == (800, 450)
    assert calls[0][1]["crop_camera"] is True
    assert closed == [scene]
    assert processed


def test_analysis_camera_preserves_sop_camera_selector(monkeypatch) -> None:
    node = _Node()
    prim = _Prim()
    resolved = {
        "type": "sop",
        "node": node,
        "prim": prim,
        "viewport_selector": "7",
    }

    result, viewport, _scene, calls, _closed, _processed, resolution_calls = _run_camera(
        monkeypatch,
        resolved=resolved,
        camera_path="/obj/geo1/camera1:7",
    )

    assert result == {"ok": True}
    assert viewport.camera_calls == [(node, "7")]
    assert viewport.frame_all_calls == 0
    assert resolution_calls == []
    assert calls[0][1]["resolution"] == (640, 360)
    assert calls[0][1]["crop_camera"] is True


def test_analysis_camera_accepts_object_id_without_changing_composition(monkeypatch) -> None:
    node = _Node()
    resolved = {
        "type": "obj",
        "node": node,
        "prim": None,
        "viewport_selector": None,
    }

    result, viewport, _scene, calls, _closed, _processed, _resolution_calls = _run_camera(
        monkeypatch,
        resolved=resolved,
        camera_path="/obj/cam1",
        capture_pass="object-id",
    )

    assert result == {"ok": True}
    assert viewport.camera_calls == [(node,)]
    assert viewport.frame_all_calls == 0
    assert calls[0][1]["capture_pass"] == "object-id"
    assert calls[0][1]["model_paths"] == ("/obj/a",)


def test_analysis_camera_forwards_curvature_settings_without_changing_composition(monkeypatch) -> None:
    node = _Node()
    resolved = {
        "type": "obj",
        "node": node,
        "prim": None,
        "viewport_selector": None,
    }

    result, viewport, _scene, calls, _closed, _processed, _resolution_calls = _run_camera(
        monkeypatch,
        resolved=resolved,
        camera_path="/obj/cam1",
        capture_pass="curvature",
        curvature_scale=2.0,
        curvature_colormap="gray",
    )

    assert result == {"ok": True}
    assert viewport.camera_calls == [(node,)]
    assert viewport.frame_all_calls == 0
    assert calls[0][1]["capture_pass"] == "curvature"
    assert calls[0][1]["curvature_scale"] == 2.0
    assert calls[0][1]["curvature_colormap"] == "gray"


def test_analysis_camera_matches_beauty_tiny_resolution_workaround(monkeypatch) -> None:
    node = _Node()
    resolved = {
        "type": "obj",
        "node": node,
        "prim": None,
        "viewport_selector": None,
    }

    result, _viewport, _scene, calls, _closed, _processed, _resolution_calls = _run_camera(
        monkeypatch,
        resolved=resolved,
        camera_path="/obj/cam1",
        scale=0.0001,
    )

    assert result == {"ok": True}
    assert calls[0][1]["resolution"] == (2, 2)
    assert calls[1] == ("resize", (Path("D:/Temp/camera.png"), (1, 1)))


def test_analysis_camera_headless_uses_flipbook_rop_without_scene_viewer(monkeypatch) -> None:
    node = _Node()
    resolved = {
        "path": "/obj/cam1",
        "type": "obj",
        "node": node,
        "prim": None,
        "viewport_selector": None,
    }
    calls = []
    destroyed = []
    rop = object()

    class _CaptureRequestError(RuntimeError):
        def __init__(self, code, message, context=None):
            super().__init__(message)
            self.code = code
            self.context = context

    runtime = {
        "CaptureRequestError": _CaptureRequestError,
        "constrained_size": lambda width, height, scale, max_width, max_height: (800, 450),
    }
    analysis_runtime = {
        "install_dso": lambda path: calls.append(("install", path)),
        "resolve_models": lambda paths, _hou, _error: tuple(paths),
        "flipbook_analysis_rop": lambda *args, **kwargs: calls.append(("render", args, kwargs)),
    }
    camera_runtime = {
        "resolve_camera": lambda path, _hou, _runtime: resolved,
        "_obj_resolution": lambda value: [1920, 1080],
        "_camera_resolution": lambda camera: list(camera.resolution()),
    }
    headless_runtime = {
        "create_flipbook_rop": lambda _hou, **kwargs: calls.append(("create", kwargs)) or rop,
        "destroy_flipbook_rop": lambda value: destroyed.append(value),
    }
    monkeypatch.setattr(analysis_camera, "_runtime", lambda: runtime)
    monkeypatch.setattr(analysis_camera, "_analysis_runtime", lambda: analysis_runtime)
    monkeypatch.setattr(analysis_camera, "_camera_runtime", lambda: camera_runtime)
    monkeypatch.setattr(analysis_camera, "_headless_runtime", lambda: headless_runtime)

    request = {
        "analysis": {
            "pass": "normal",
            "model_paths": ["/obj/a"],
            "unit": None,
            "curvature_scale": 1.0,
            "curvature_colormap": "rg",
        },
        "dso_path": "D:/cache/capture.dll",
        "generation": "abc123",
        "camera_path": "/obj/cam1",
        "png_path": "D:/Temp/camera.png",
        "trigger_path": "D:/Temp/trigger.png",
        "scale": 0.5,
        "max_width": 800,
        "max_height": 600,
        "pane": None,
    }
    hou = SimpleNamespace(isUIAvailable=lambda: False)

    result = analysis_camera._run(request, hou)

    assert result == {"ok": True}
    assert ("create", {"camera_path": "/obj/cam1", "resolution": (800, 450)}) in calls
    render = next(item for item in calls if item[0] == "render")
    assert render[1] == (rop,)
    assert render[2]["capture_pass"] == "normal"
    assert render[2]["model_paths"] == ("/obj/a",)
    assert destroyed == [rop]
