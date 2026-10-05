from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from houbridge.houdini.scripts.capture import headless_camera


class _ParmTemplate:
    def __init__(self, label: str) -> None:
        self._label = label

    def label(self) -> str:
        return self._label


class _Parm:
    def __init__(self, name: str, label: str) -> None:
        self._name = name
        self._template = _ParmTemplate(label)
        self.value = None

    def name(self) -> str:
        return self._name

    def parmTemplate(self):
        return self._template

    def set(self, value) -> None:
        self.value = value


class _Rop:
    def __init__(self, output_path: Path | None = None) -> None:
        self.camera = _Parm("camera", "Camera")
        self.resx = _Parm("resx", "Resolution X")
        self.resy = _Parm("resy", "Resolution Y")
        self.output_path = output_path
        self.destroyed = False
        self.render_calls = []

    def parm(self, name: str):
        return {"camera": self.camera, "resx": self.resx, "resy": self.resy}.get(name)

    def parmTuple(self, _name: str):
        return None

    def parms(self):
        return (self.camera, self.resx, self.resy)

    def render(self, **kwargs) -> None:
        self.render_calls.append(kwargs)
        if self.output_path is not None:
            self.output_path.write_bytes(b"png")

    def destroy(self) -> None:
        self.destroyed = True


class _Out:
    def __init__(self, rop: _Rop) -> None:
        self.rop = rop
        self.calls = []

    def createNode(self, node_type: str, name: str):
        self.calls.append((node_type, name))
        return self.rop


def test_create_flipbook_rop_sets_camera_and_resolution() -> None:
    rop = _Rop()
    out = _Out(rop)
    hou = SimpleNamespace(node=lambda path: out if path == "/out" else None)

    created = headless_camera.create_flipbook_rop(
        hou,
        camera_path="/obj/geo1/camera1:7",
        resolution=(640, 360),
    )

    assert created is rop
    assert out.calls[0][0] == "flipbook"
    assert rop.camera.value == "/obj/geo1/camera1:7"
    assert rop.resx.value == 640
    assert rop.resy.value == 360


def test_render_flipbook_rop_renders_one_frame_and_requires_png(tmp_path: Path) -> None:
    output = tmp_path / "camera.png"
    rop = _Rop(output)
    hou = SimpleNamespace(frame=lambda: 12)

    headless_camera.render_flipbook_rop(rop, output, hou)

    assert rop.render_calls == [
        {
            "frame_range": (12, 12),
            "output_file": str(output),
            "ignore_inputs": True,
            "verbose": True,
            "output_progress": True,
        }
    ]
    assert output.is_file()


def test_camera_headless_dispatch_uses_resolved_camera_path_without_ui(monkeypatch, tmp_path: Path) -> None:
    from houbridge.houdini.scripts.capture import camera

    output = tmp_path / "camera.png"
    rop = object()
    calls = []
    destroyed = []
    monkeypatch.setattr(camera, "_obj_resolution", lambda _node: [1920, 1080])
    monkeypatch.setattr(
        camera,
        "_headless_runtime",
        lambda: {
            "create_flipbook_rop": lambda _hou, **kwargs: calls.append(("create", kwargs)) or rop,
            "render_flipbook_rop": lambda value, path, _hou: calls.append(("render", value, path)),
            "destroy_flipbook_rop": lambda value: destroyed.append(value),
        },
    )
    runtime = {
        "CaptureRequestError": RuntimeError,
        "constrained_size": lambda width, height, scale, max_width, max_height: (960, 540),
    }
    request = {
        "pane": None,
        "scale": 0.5,
        "max_width": 2048,
        "max_height": 2048,
        "png_path": str(output),
    }
    resolved = {
        "path": "/obj/cam1",
        "type": "obj",
        "node": object(),
        "prim": None,
        "viewport_selector": None,
    }
    hou = SimpleNamespace(isUIAvailable=lambda: False)

    camera.capture_camera(request, resolved, hou, runtime)

    assert calls == [
        ("create", {"camera_path": "/obj/cam1", "resolution": (960, 540)}),
        ("render", rop, output),
    ]
    assert destroyed == [rop]


def test_camera_headless_rejects_pane_selection_before_creating_rop(monkeypatch) -> None:
    from houbridge.houdini.scripts.capture import camera, runtime as capture_runtime

    monkeypatch.setattr(
        camera,
        "_headless_runtime",
        lambda: (_ for _ in ()).throw(AssertionError("headless runtime should not be loaded")),
    )
    request = {
        "pane": "panetab4",
        "scale": 1.0,
        "max_width": 2048,
        "max_height": 2048,
        "png_path": "camera.png",
    }
    resolved = {
        "path": "/obj/cam1",
        "type": "obj",
        "node": object(),
        "prim": None,
        "viewport_selector": None,
    }
    hou = SimpleNamespace(isUIAvailable=lambda: False)
    api = {
        "CaptureRequestError": capture_runtime.CaptureRequestError,
        "constrained_size": lambda *args: (1920, 1080),
    }

    try:
        camera.capture_camera(request, resolved, hou, api)
    except capture_runtime.CaptureRequestError as exc:
        assert exc.code == "viewport_unavailable"
    else:
        raise AssertionError("expected viewport_unavailable")
