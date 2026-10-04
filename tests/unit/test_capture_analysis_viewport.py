from __future__ import annotations

from types import SimpleNamespace

import pytest

from houbridge.houdini.scripts.capture import analysis_viewport


class _Viewport:
    def geometry(self):
        return (0, 0, 1280, 720)


class _Scene:
    def __init__(self, viewport: _Viewport) -> None:
        self.viewport = viewport

    def curViewport(self):
        return self.viewport


@pytest.mark.parametrize("capture_pass", ["depth", "grid", "normal", "object-id", "curvature"])
def test_active_analysis_viewport_uses_clone_created_after_dso_install(monkeypatch, capture_pass: str) -> None:
    viewport = _Viewport()
    source_scene = object()
    cloned_scene = _Scene(viewport)
    events: list[object] = []
    flipbook_calls = []

    class _CaptureRequestError(RuntimeError):
        pass

    def install_dso(_path) -> None:
        events.append("install")

    def resolve_scene_viewer(_hou, _pane):
        events.append("resolve")
        return source_scene

    def clone_scene_viewer(source, _hou, _widgets):
        assert source is source_scene
        events.append("clone")
        return cloned_scene

    runtime = {
        "CaptureRequestError": _CaptureRequestError,
        "resolve_scene_viewer": resolve_scene_viewer,
        "clone_scene_viewer": clone_scene_viewer,
        "close_scene_viewer": lambda scene: events.append(("close", scene)),
        "process_events": lambda _hou, _widgets: events.append("process"),
        "constrained_size": lambda width, height, scale, max_width, max_height: (width, height),
    }
    analysis_runtime = {
        "install_dso": install_dso,
        "resolve_models": lambda paths, _hou, _error: tuple(paths),
        "flipbook_analysis": lambda *args, **kwargs: flipbook_calls.append((args, kwargs)),
    }
    monkeypatch.setattr(analysis_viewport, "_runtime", lambda: runtime)
    monkeypatch.setattr(analysis_viewport, "_analysis_runtime", lambda: analysis_runtime)

    hou = SimpleNamespace(
        geometryViewportType=SimpleNamespace(
            Top="top",
            Bottom="bottom",
            Front="front",
            Back="back",
            Left="left",
            Right="right",
            Perspective="persp",
            UV="uv",
        ),
        geometryViewportLayout=SimpleNamespace(Single="single"),
    )
    request = {
        "analysis": {
            "pass": capture_pass,
            "model_paths": [],
            "unit": 1.0 if capture_pass == "grid" else None,
            "curvature_scale": 1.0,
            "curvature_colormap": "rg",
        },
        "png_paths": ["D:/Temp/viewport.png"],
        "trigger_paths": ["D:/Temp/trigger.png"],
        "requested_views": [],
        "dso_path": "D:/cache/capture.dll",
        "generation": "abc123",
        "scale": 1.0,
        "max_width": 2048,
        "max_height": 2048,
        "pane": None,
    }

    assert analysis_viewport._run(request, hou, object()) == {"ok": True}
    assert events[:3] == ["install", "resolve", "clone"]
    assert events[-1] == ("close", cloned_scene)
    assert flipbook_calls[0][0][:2] == (cloned_scene, viewport)
    assert flipbook_calls[0][1]["capture_pass"] == capture_pass
