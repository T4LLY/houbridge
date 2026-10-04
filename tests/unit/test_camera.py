from __future__ import annotations

import json
import struct
import zlib
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from houbridge.capture.artifacts import CaptureArtifactPublisher
from houbridge.capture.camera import CameraService
from houbridge.config import ScreenshotConfig
from houbridge.errors import BridgeError
from houbridge.houdini.transport import HoudiniTarget
from houbridge.temporary_artifact import TemporaryArtifactService
from houbridge.temporary_workspace import TemporaryWorkspaceService


def _png(width: int, height: int) -> bytes:
    signature = b"\x89PNG\r\n\x1a\n"
    ihdr_data = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return (
            struct.pack(">I", len(data))
            + body
            + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
        )

    raw = b"\x00" + b"\x00\x00\x00\x00" * width
    return (
        signature
        + chunk(b"IHDR", ihdr_data)
        + chunk(b"IDAT", zlib.compress(raw * height))
        + chunk(b"IEND", b"")
    )


class _Session(SimpleNamespace):
    target = HoudiniTarget("127.0.0.1", 49152)


class _CameraTransport:
    def __init__(self) -> None:
        self.requests: list[dict[str, object]] = []
        self.failure: dict[str, object] | None = None

    def execute_script(self, _target, runner: Path):
        workspace = runner.parent
        request = json.loads((workspace / "request.json").read_text(encoding="utf-8"))
        self.requests.append(request)
        if self.failure is not None:
            payload = self.failure
        elif request["mode"] == "list":
            payload = {
                "ok": True,
                "cameras": [
                    {"path": "/obj/cam1", "type": "obj", "resolution": [1920, 1080]},
                    {
                        "path": "/obj/geo1/camera1:0",
                        "type": "sop",
                        "resolution": [1280, 720],
                    },
                ],
            }
        elif request["mode"] == "detail":
            payload = {
                "ok": True,
                "camera": {
                    "path": request["camera_path"],
                    "type": "obj",
                    "resolution": [1920, 1080],
                    "projection": "perspective",
                    "focal_length": 50.0,
                    "aperture": 41.4214,
                    "pixel_aspect": 1.0,
                    "near_clip": 0.1,
                    "far_clip": 1000.0,
                    "focus_distance": 5.0,
                    "f_stop": 5.6,
                },
            }
        else:
            Path(request["png_path"]).write_bytes(_png(960, 540))
            payload = {"ok": True}
        Path(request["result_path"]).write_text(
            json.dumps(payload, separators=(",", ":")),
            encoding="utf-8",
        )


def _service(
    tmp_path: Path,
    transport=None,
    *,
    analysis_backend=None,
) -> tuple[CameraService, TemporaryArtifactService]:
    artifacts = TemporaryArtifactService(temp_root=tmp_path / "os-temp")
    publisher = CaptureArtifactPublisher(
        artifacts,
        1,
        now_timestamp=lambda: 10_000.0,
        now_datetime=lambda: datetime(2026, 9, 28, 11, 45),
    )
    return (
        CameraService(
            transport or _CameraTransport(),
            ScreenshotConfig(retention_hours=1, max_width=2048, max_height=2048),
            publisher,
            workspaces=TemporaryWorkspaceService(temp_root=tmp_path / "os-temp"),
            analysis_backend=analysis_backend,
        ),
        artifacts,
    )


def test_camera_list_and_detail_return_bounded_public_shapes(tmp_path: Path) -> None:
    transport = _CameraTransport()
    service, _artifacts = _service(tmp_path, transport)

    listed = service.list(_Session())
    detail = service.detail(_Session(), "/obj/cam1")

    assert listed == {
        "cameras": [
            {"path": "/obj/cam1", "type": "obj", "resolution": [1920, 1080]},
            {"path": "/obj/geo1/camera1:0", "type": "sop", "resolution": [1280, 720]},
        ]
    }
    assert detail == {
        "path": "/obj/cam1",
        "type": "obj",
        "resolution": [1920, 1080],
        "projection": "perspective",
        "focal_length": 50.0,
        "aperture": 41.4214,
        "pixel_aspect": 1.0,
        "near_clip": 0.1,
        "far_clip": 1000.0,
        "focus_distance": 5.0,
        "f_stop": 5.6,
    }
    assert transport.requests[0]["mode"] == "list"
    assert "pane" not in transport.requests[0]
    assert transport.requests[1]["mode"] == "detail"
    assert transport.requests[1]["camera_path"] == "/obj/cam1"


def test_camera_capture_forwards_pane_and_scale_and_publishes_camera_png(tmp_path: Path) -> None:
    transport = _CameraTransport()
    service, artifacts = _service(tmp_path, transport)

    result = service.capture(
        _Session(),
        "/obj/cam1",
        scale=0.5,
        pane="panetab4",
    )

    path = Path(result["path"])
    assert path.name == "camera20260928-1145-001.png"
    assert path.read_bytes() == _png(960, 540)
    request = transport.requests[0]
    assert request["mode"] == "capture"
    assert request["camera_path"] == "/obj/cam1"
    assert request["scale"] == 0.5
    assert request["pane"] == "panetab4"
    assert request["max_width"] == 2048
    assert request["max_height"] == 2048
    assert [item.name for item in (artifacts.root / "capture").iterdir()] == [path.name]


def test_camera_service_rejects_invalid_path_before_transport(tmp_path: Path) -> None:
    transport = _CameraTransport()
    service, _artifacts = _service(tmp_path, transport)

    with pytest.raises(BridgeError) as caught:
        service.detail(_Session(), "obj/cam1")

    assert caught.value.code == "camera_path_invalid"
    assert transport.requests == []


def test_camera_service_preserves_structured_scene_viewer_error(tmp_path: Path) -> None:
    transport = _CameraTransport()
    transport.failure = {
        "ok": False,
        "code": "scene_viewer_ambiguous",
        "message": "Multiple Scene Viewer panes are available; specify --pane.",
        "context": {
            "panes": [
                {"name": "panetab1", "current_node": None, "viewports": []},
                {"name": "panetab4", "current_node": None, "viewports": []},
            ]
        },
    }
    service, _artifacts = _service(tmp_path, transport)

    with pytest.raises(BridgeError) as caught:
        service.capture(_Session(), "/obj/cam1")

    assert caught.value.code == "scene_viewer_ambiguous"
    assert caught.value.context == transport.failure["context"]


def test_camera_injected_code_reuses_capture_runtime_and_preserves_camera_framing() -> None:
    from houbridge.houdini.scripts.capture import camera, runtime

    source = Path(camera.__file__).read_text(encoding="utf-8")
    runtime_source = Path(runtime.__file__).read_text(encoding="utf-8")

    assert 'runtime["resolve_scene_viewer"]' in source
    assert 'runtime["clone_scene_viewer"]' in source
    assert 'runtime["close_scene_viewer"]' in source
    assert 'runtime["flipbook_png"]' in source
    assert 'runtime["constrained_size"]' in source
    assert "viewport.setCamera(resolved[\"node\"])" in source
    assert 'viewport.setCamera(resolved["node"], resolved["viewport_selector"])' in source
    assert "frameAll(" not in source
    assert 'hou.nodeType(hou.objNodeTypeCategory(), "cam")' not in source
    assert 'hou.objNodeTypeCategory(), "cam"' in source
    assert 'hou.sopNodeTypeCategory(), "camera"' in source
    assert "isinstance(prim, hou.CameraPrim)" in source
    assert '"type": "obj"' in source
    assert '"type": "sop"' in source
    assert "output_resolution = constrained_size(" in source
    assert "flipbook_resolution = output_resolution" in source
    assert "if min(output_resolution) < 2:" in source
    assert "flipbook_resolution=flipbook_resolution" in source
    assert "scale=output_scale" in source
    assert "crop_camera=True" in source

    assert "settings.useResolution(True)" in runtime_source
    assert "settings.outputZoom(100)" in runtime_source
    assert "settings.cropOutMaskOverlay(True)" in runtime_source


def test_camera_sop_name_selector_rejects_duplicate_names() -> None:
    from houbridge.houdini.scripts.capture import camera, runtime

    class _CameraPrim:
        def __init__(self, number: int) -> None:
            self._number = number

        def number(self) -> int:
            return self._number

        def attribValue(self, name: str):
            assert name == "name"
            return "shot"

        def camera(self):
            return SimpleNamespace(resolution=lambda: (1280, 720))

    class _Geometry:
        def prims(self):
            return (_CameraPrim(2), _CameraPrim(5))

    class _Node:
        def geometry(self):
            return _Geometry()

        def path(self) -> str:
            return "/obj/geo1/camera1"

    fake_hou = SimpleNamespace(CameraPrim=_CameraPrim)
    runtime_api = {"CaptureRequestError": runtime.CaptureRequestError}

    with pytest.raises(runtime.CaptureRequestError) as caught:
        camera._select_sop_camera(_Node(), "shot", fake_hou, runtime_api)

    assert caught.value.code == "camera_ambiguous"
    assert caught.value.context == {
        "cameras": [
            {"path": "/obj/geo1/camera1:2", "type": "sop", "resolution": [1280, 720]},
            {"path": "/obj/geo1/camera1:5", "type": "sop", "resolution": [1280, 720]},
        ]
    }


def test_camera_analysis_uses_shared_backend_and_existing_publication(tmp_path: Path) -> None:
    from houbridge.capture.analysis import build_analysis_request

    class _AnalysisBackend:
        def __init__(self) -> None:
            self.calls = []

        def render_viewport(self, session, request, source, workspace) -> None:
            raise AssertionError("viewport route not expected")

        def render_camera(self, session, request, source, workspace) -> None:
            self.calls.append((session, request, source, workspace))
            source.png_path.write_bytes(_png(960, 540))

    transport = _CameraTransport()
    backend = _AnalysisBackend()
    service, artifacts = _service(tmp_path, transport, analysis_backend=backend)
    request = build_analysis_request("depth")

    result = service.capture(
        _Session(),
        "/obj/cam1",
        scale=0.5,
        pane="panetab4",
        analysis=request,
    )

    assert Path(result["path"]).name == "camera20260928-1145-001.png"
    assert transport.requests == []
    assert len(backend.calls) == 1
    source = backend.calls[0][2]
    assert source.camera_path == "/obj/cam1"
    assert source.scale == 0.5
    assert source.pane == "panetab4"
    assert len(list((artifacts.root / "capture").iterdir())) == 1
