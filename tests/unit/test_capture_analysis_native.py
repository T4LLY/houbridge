from __future__ import annotations

import json
import struct
import zlib
from pathlib import Path
from types import SimpleNamespace


from houbridge.capture.analysis import CameraAnalysisSource, ViewportAnalysisSource, build_analysis_request
from houbridge.capture.analysis_native import NativeAnalysisCaptureBackend
from houbridge.capture.models import ScreenshotPreset
from houbridge.capture.native import NativeCaptureArtifact
from houbridge.houdini.transport import HoudiniTarget
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
    return signature + chunk(b"IHDR", ihdr_data) + chunk(b"IDAT", zlib.compress(raw * height)) + chunk(b"IEND", b"")


class _Builder:
    def __init__(self, artifact: NativeCaptureArtifact) -> None:
        self.artifact = artifact
        self.calls = []

    def ensure(self, **kwargs):
        self.calls.append(kwargs)
        return self.artifact


class _Transport:
    executable = "hcommand-test"

    def __init__(self) -> None:
        self.requests = []

    def subprocess_environment(self):
        return {"PATH": "test"}

    def execute_script(self, _target, runner: Path):
        request_path = runner.parent / "analysis-request.json"
        request = json.loads(request_path.read_text(encoding="utf-8"))
        self.requests.append(request)
        outputs = request.get("png_paths")
        if outputs is None:
            outputs = [request["png_path"]]
        for output in outputs:
            Path(output).write_bytes(_png(320, 180))
        Path(request["result_path"]).write_text('{"ok":true}', encoding="utf-8")


def _session():
    return SimpleNamespace(
        target=HoudiniTarget("127.0.0.1", 1714),
        probe=SimpleNamespace(version="22.0.429"),
    )


def test_native_backend_builds_cached_dso_and_forwards_viewport_request(tmp_path: Path) -> None:
    artifact = NativeCaptureArtifact(
        path=tmp_path / "capture.dll",
        generation="abc123",
        houdini_build="22.0.429",
    )
    artifact.path.write_bytes(b"dll")
    builder = _Builder(artifact)
    transport = _Transport()
    backend = NativeAnalysisCaptureBackend(transport, builder)
    workspace = TemporaryWorkspaceService(temp_root=tmp_path).allocate(prefix="analysis")
    output = workspace.path_for("capture-000.png")
    request = build_analysis_request(
        "grid",
        model_paths=("/obj/a", "/obj/b"),
        unit=0.5,
    )
    assert request is not None

    backend.render_viewport(
        _session(),
        request,
        ViewportAnalysisSource(
            png_paths=(output,),
            requested_views=("front",),
            scale=1.5,
            max_width=2048,
            max_height=1024,
            preset=ScreenshotPreset(view="front"),
            pane="panetab4",
        ),
        workspace,
    )

    assert output.is_file()
    assert builder.calls == [
        {
            "houdini_build": "22.0.429",
            "hcommand": "hcommand-test",
            "environ": {"PATH": "test"},
        }
    ]
    sent = transport.requests[0]
    assert sent["generation"] == "abc123"
    assert sent["analysis"]["pass"] == "grid"
    assert sent["analysis"]["model_paths"] == ["/obj/a", "/obj/b"]
    assert sent["analysis"]["unit"] == 0.5
    assert sent["requested_views"] == ["front"]
    assert sent["scale"] == 1.5
    assert sent["pane"] == "panetab4"


def test_native_backend_forwards_camera_depth_grid_request(tmp_path: Path) -> None:
    artifact = NativeCaptureArtifact(
        path=tmp_path / "capture.dll",
        generation="abc123",
        houdini_build="22.0.429",
    )
    artifact.path.write_bytes(b"dll")
    builder = _Builder(artifact)
    transport = _Transport()
    backend = NativeAnalysisCaptureBackend(transport, builder)
    workspace = TemporaryWorkspaceService(temp_root=tmp_path).allocate(prefix="analysis")
    output = workspace.path_for("camera.png")
    request = build_analysis_request(
        "grid",
        model_paths=("/obj/a", "/obj/b"),
        unit=0.25,
    )
    assert request is not None

    backend.render_camera(
        _session(),
        request,
        CameraAnalysisSource(
            png_path=output,
            camera_path="/obj/geo1/camera1:2",
            scale=0.5,
            max_width=1920,
            max_height=1080,
            pane="panetab4",
        ),
        workspace,
    )

    assert output.is_file()
    assert len(builder.calls) == 1
    sent = transport.requests[0]
    assert sent["analysis"]["pass"] == "grid"
    assert sent["analysis"]["model_paths"] == ["/obj/a", "/obj/b"]
    assert sent["analysis"]["unit"] == 0.25
    assert sent["camera_path"] == "/obj/geo1/camera1:2"
    assert sent["scale"] == 0.5
    assert sent["max_width"] == 1920
    assert sent["max_height"] == 1080
    assert sent["pane"] == "panetab4"




def test_native_backend_forwards_curvature_for_viewport_and_camera(tmp_path: Path) -> None:
    artifact = NativeCaptureArtifact(
        path=tmp_path / "capture.dll",
        generation="curvature123",
        houdini_build="22.0.429",
    )
    artifact.path.write_bytes(b"dll")
    builder = _Builder(artifact)
    transport = _Transport()
    backend = NativeAnalysisCaptureBackend(transport, builder)
    workspace = TemporaryWorkspaceService(temp_root=tmp_path).allocate(prefix="analysis")
    request = build_analysis_request(
        "curvature",
        model_paths=("/obj/a",),
        curvature_scale=2.0,
        curvature_colormap="gray",
    )
    assert request is not None

    backend.render_viewport(
        _session(),
        request,
        ViewportAnalysisSource(
            png_paths=(workspace.path_for("viewport-curvature.png"),),
            requested_views=(),
            scale=1.0,
            max_width=2048,
            max_height=2048,
            preset=ScreenshotPreset(),
            pane=None,
        ),
        workspace,
    )
    backend.render_camera(
        _session(),
        request,
        CameraAnalysisSource(
            png_path=workspace.path_for("camera-curvature.png"),
            camera_path="/obj/cam1",
            scale=1.0,
            max_width=2048,
            max_height=2048,
            pane=None,
        ),
        workspace,
    )

    assert [item["analysis"]["pass"] for item in transport.requests] == [
        "curvature",
        "curvature",
    ]
    assert all(item["analysis"]["curvature_scale"] == 2.0 for item in transport.requests)
    assert all(item["analysis"]["curvature_colormap"] == "gray" for item in transport.requests)
    assert len(builder.calls) == 2

def test_native_backend_forwards_normal_for_viewport_and_camera(tmp_path: Path) -> None:
    artifact = NativeCaptureArtifact(
        path=tmp_path / "capture.dll",
        generation="normal123",
        houdini_build="22.0.429",
    )
    artifact.path.write_bytes(b"dll")
    builder = _Builder(artifact)
    transport = _Transport()
    backend = NativeAnalysisCaptureBackend(transport, builder)
    workspace = TemporaryWorkspaceService(temp_root=tmp_path).allocate(prefix="analysis")
    request = build_analysis_request("normal", model_paths=("/obj/a",))
    assert request is not None

    backend.render_viewport(
        _session(),
        request,
        ViewportAnalysisSource(
            png_paths=(workspace.path_for("viewport-normal.png"),),
            requested_views=(),
            scale=1.0,
            max_width=2048,
            max_height=2048,
            preset=ScreenshotPreset(),
            pane=None,
        ),
        workspace,
    )
    backend.render_camera(
        _session(),
        request,
        CameraAnalysisSource(
            png_path=workspace.path_for("camera-normal.png"),
            camera_path="/obj/cam1",
            scale=1.0,
            max_width=2048,
            max_height=2048,
            pane=None,
        ),
        workspace,
    )

    assert [item["analysis"]["pass"] for item in transport.requests] == ["normal", "normal"]
    assert all(item["analysis"]["model_paths"] == ["/obj/a"] for item in transport.requests)
    assert len(builder.calls) == 2


def test_native_backend_forwards_object_id_for_viewport_and_camera(tmp_path: Path) -> None:
    artifact = NativeCaptureArtifact(
        path=tmp_path / "capture.dll",
        generation="objectid123",
        houdini_build="22.0.429",
    )
    artifact.path.write_bytes(b"dll")
    builder = _Builder(artifact)
    transport = _Transport()
    backend = NativeAnalysisCaptureBackend(transport, builder)
    workspace = TemporaryWorkspaceService(temp_root=tmp_path).allocate(prefix="analysis")
    request = build_analysis_request(
        "object-id",
        model_paths=("/obj/target_a", "/obj/target_b"),
    )
    assert request is not None

    backend.render_viewport(
        _session(),
        request,
        ViewportAnalysisSource(
            png_paths=(workspace.path_for("viewport-object-id.png"),),
            requested_views=(),
            scale=1.0,
            max_width=2048,
            max_height=2048,
            preset=ScreenshotPreset(),
            pane=None,
        ),
        workspace,
    )
    backend.render_camera(
        _session(),
        request,
        CameraAnalysisSource(
            png_path=workspace.path_for("camera-object-id.png"),
            camera_path="/obj/cam1",
            scale=1.0,
            max_width=2048,
            max_height=2048,
            pane=None,
        ),
        workspace,
    )

    assert [item["analysis"]["pass"] for item in transport.requests] == [
        "object-id",
        "object-id",
    ]
    assert all(
        item["analysis"]["model_paths"] == ["/obj/target_a", "/obj/target_b"]
        for item in transport.requests
    )
    assert len(builder.calls) == 2


def test_object_id_renderer_reuses_shared_displayed_geometry_filter() -> None:
    from houbridge.houdini.scripts.capture import native

    source = (Path(native.__file__).parent / "object_id.h").read_text(encoding="utf-8")

    assert "houbridge_displayed_geometry::for_each_polygon_mesh(" in source
    assert "viewport, targets," in source
    assert "viewport.getNumOpaqueObjects" not in source
    assert "rv->setBlendEnable(false);" in source


def test_curvature_renderer_reuses_shared_displayed_geometry_and_validated_mapping() -> None:
    from houbridge.houdini.scripts.capture import native

    source = (Path(native.__file__).parent / "curvature.h").read_text(encoding="utf-8")

    assert "houbridge_displayed_geometry::for_each_polygon_mesh(" in source
    assert "viewport, targets," in source
    assert "viewport.getNumOpaqueObjects" not in source
    assert "0.90 * static_cast<double>(magnitudes.size() - 1)" in source
    assert "mapped * scale_multiplier" in source
    assert "red = mapped >= 0.0 ? strength : 0.0;" in source
    assert "green = mapped < 0.0 ? strength : 0.0;" in source
    assert "blue = 0.0;" in source
