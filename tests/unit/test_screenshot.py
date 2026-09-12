from __future__ import annotations

import json
import runpy
import struct
import zlib
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from houbridge.capture.artifacts import CaptureArtifactPublisher
from houbridge.capture.png import png_size
from houbridge.capture.screenshot import ScreenshotService
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
    return signature + chunk(b"IHDR", ihdr_data) + chunk(b"IDAT", zlib.compress(raw * height)) + chunk(b"IEND", b"")


class _Session(SimpleNamespace):
    target = HoudiniTarget("127.0.0.1", 49152)


class _CaptureTransport:
    def __init__(self, *, width: int = 64, height: int = 32) -> None:
        self.width = width
        self.height = height
        self.requests: list[dict[str, object]] = []

    def execute_script(self, _target, runner: Path):
        workspace = runner.parent
        request = json.loads((workspace / "request.json").read_text(encoding="utf-8"))
        self.requests.append(request)
        for path in request["png_paths"]:
            Path(path).write_bytes(_png(self.width, self.height))
        bounds_path = request.get("bounds_path")
        if bounds_path:
            bounds = {
                "width": self.width,
                "height": self.height,
                "coordinate_space": "final_png_top_left",
                "source_width": self.width * 2,
                "source_height": self.height * 2,
                "scale_x": 0.5,
                "scale_y": 0.5,
                "areas": [
                    {
                        "type": "scene_viewer",
                        "name": "pane1",
                        "x": 0,
                        "y": 0,
                        "width": self.width,
                        "height": self.height,
                        "viewports": [
                            {
                                "type": "persp",
                                "name": "persp1",
                                "x": 0,
                                "y": 0,
                                "width": self.width,
                                "height": self.height,
                            }
                        ],
                    }
                ],
            }
            crop = request["preset"].get("crop")
            if crop:
                bounds["cropped_from"] = crop
            Path(bounds_path).write_text(
                json.dumps(bounds, ensure_ascii=False, separators=(",", ":")),
                encoding="utf-8",
            )
        Path(request["result_path"]).write_text('{"ok":true}', encoding="utf-8")


def _service(tmp_path: Path, transport=None) -> ScreenshotService:
    artifacts = TemporaryArtifactService(temp_root=tmp_path / "os-temp")
    publisher = CaptureArtifactPublisher(
        artifacts,
        1,
        now_timestamp=lambda: 10_000.0,
        now_datetime=lambda: datetime(2026, 9, 11, 19, 42),
    )
    return ScreenshotService(
        transport or _CaptureTransport(),
        ScreenshotConfig(retention_hours=1, max_width=2048, max_height=2048),
        publisher,
        workspaces=TemporaryWorkspaceService(temp_root=tmp_path / "os-temp"),
    )


def test_png_size_reads_ihdr(tmp_path: Path) -> None:
    path = tmp_path / "image.png"
    path.write_bytes(_png(320, 180))
    assert png_size(path) == (320, 180)


def test_scale_is_applied_before_maximum_dimension_clamp() -> None:
    from houbridge.houdini.scripts.capture import runtime

    functions = runpy.run_path(runtime.__file__)
    assert functions["constrained_size"](1000, 500, 3.0, 2048, 2048) == (2048, 1024)
    assert functions["constrained_size"](320, 180, 2.0, 2048, 2048) == (640, 360)


def test_directed_viewport_capture_uses_readable_sequential_names(tmp_path: Path) -> None:
    transport = _CaptureTransport()
    service = _service(tmp_path, transport)

    result = service.capture_viewport(_Session(), views=("front", "right"))

    assert [item["view"] for item in result["captures"]] == ["front", "right"]
    paths = [Path(item["path"]) for item in result["captures"]]
    assert [path.name for path in paths] == [
        "viewport20260911-1942-001.png",
        "viewport20260911-1942-002.png",
    ]
    assert all(path.parent == tmp_path / "os-temp" / "houbridge" / "artifacts" / "capture" for path in paths)
    assert transport.requests[0]["requested_views"] == ["front", "right"]


def test_preset_view_is_used_but_explicit_direction_overrides_it(tmp_path: Path) -> None:
    preset = tmp_path / "preset.json"
    preset.write_text('{"view":"uv","shading":"smoothwire"}', encoding="utf-8")
    transport = _CaptureTransport()
    service = _service(tmp_path, transport)

    service.capture_viewport(_Session(), preset_path=preset)
    service.capture_viewport(_Session(), views=("front",), preset_path=preset)

    assert transport.requests[0]["requested_views"] == ["uv"]
    assert transport.requests[1]["requested_views"] == ["front"]
    assert transport.requests[1]["preset"]["shading"] == "smoothwire"


def test_quad_is_one_capture_and_injected_code_uses_clone_fixed_views_and_captions(tmp_path: Path) -> None:
    service = _service(tmp_path)
    result = service.capture_viewport(_Session(), quad=True)

    assert set(result) == {"path"}
    from houbridge.houdini.scripts.capture import viewport

    source = Path(viewport.__file__).read_text(encoding="utf-8")
    assert "source_scene.clone" not in source
    runtime_source = Path(viewport.__file__).with_name("runtime.py").read_text(encoding="utf-8")
    assert "source_scene.clone()" in runtime_source
    assert "hou.geometryViewportLayout.Quad" in source
    for entry in ('("top", 0, 0)', '("persp", 1, 0)', '("front", 0, 1)', '("right", 1, 1)'):
        assert entry in source
    assert "_draw_caption(cell, label" in source


def test_active_view_without_preset_does_not_clone_or_change_live_view(tmp_path: Path) -> None:
    transport = _CaptureTransport()
    service = _service(tmp_path, transport)

    service.capture_viewport(_Session())

    assert transport.requests[0]["requested_views"] == []
    assert transport.requests[0]["quad"] is False
    from houbridge.houdini.scripts.capture import viewport

    source = Path(viewport.__file__).read_text(encoding="utf-8")
    assert "source_scene.curViewport()" in source
    assert "viewport.changeType(view_types[view_name])" in source
    assert ".homeAll(" not in source
    assert ".frameAll(" not in source


def test_window_capture_returns_inline_final_image_bounds_and_no_sidecar_artifact(tmp_path: Path) -> None:
    service = _service(tmp_path)

    result = service.capture_window(_Session())

    assert set(result) == {"path", "bounds"}
    path = Path(result["path"])
    assert path.name == "window20260911-1942-001.png"
    assert result["bounds"]["width"] == 64
    assert result["bounds"]["height"] == 32
    assert result["bounds"]["coordinate_space"] == "final_png_top_left"
    assert list(path.parent.glob("*.json")) == []


def test_explicit_window_crop_overrides_preset_and_bounds_report_effective_selector(tmp_path: Path) -> None:
    preset = tmp_path / "window.json"
    preset.write_text('{"crop":"network_editor"}', encoding="utf-8")
    transport = _CaptureTransport()
    service = _service(tmp_path, transport)

    result = service.capture_window(
        _Session(),
        crop="viewport:persp:0",
        preset_path=preset,
    )

    assert transport.requests[0]["preset"]["crop"] == "viewport:persp:0"
    assert result["bounds"]["cropped_from"] == "viewport:persp:0"


def test_crop_selector_rejects_ambiguity_and_supports_zero_based_suffix() -> None:
    from houbridge.houdini.scripts.capture import window

    functions = runpy.run_path(window.__file__)
    choose = functions["_choose_crop_candidate"]
    areas = [
        {"type": "network_editor", "name": "pane1", "x": 0, "y": 0, "width": 10, "height": 10},
        {"type": "network_editor", "name": "pane2", "x": 10, "y": 0, "width": 10, "height": 10},
    ]

    with pytest.raises(RuntimeError, match="ambiguous"):
        choose("network_editor", areas)
    assert choose("network_editor:1", areas)["name"] == "pane2"


def test_crop_happens_before_scale_and_bounds_are_transformed_in_injected_code() -> None:
    from houbridge.houdini.scripts.capture import window

    source = Path(window.__file__).read_text(encoding="utf-8")
    assert "pixmap = pixmap.copy(" in source
    assert source.index("pixmap = pixmap.copy(") < source.index("constrained_size(")
    assert "logical_to_source_x" in source
    assert "_finalize_areas(" in source
    assert 'bounds["cropped_from"]' in source


def test_capture_rejects_invalid_scale_and_viewport_crop_preset_before_transport(tmp_path: Path) -> None:
    transport = _CaptureTransport()
    service = _service(tmp_path, transport)
    crop = tmp_path / "crop.json"
    crop.write_text('{"crop":"network_editor"}', encoding="utf-8")

    with pytest.raises(BridgeError) as scale:
        service.capture_viewport(_Session(), scale=0)
    with pytest.raises(BridgeError) as preset:
        service.capture_viewport(_Session(), preset_path=crop)

    assert scale.value.code == "invalid_screenshot_scale"
    assert preset.value.code == "screenshot_crop_requires_window"
    assert transport.requests == []


def test_artifact_publication_failure_does_not_leave_successful_png(tmp_path: Path, monkeypatch) -> None:
    artifacts = TemporaryArtifactService(temp_root=tmp_path / "os-temp")
    publisher = CaptureArtifactPublisher(
        artifacts,
        1,
        now_timestamp=lambda: 10_000.0,
        now_datetime=lambda: datetime(2026, 9, 11, 19, 42),
    )
    service = ScreenshotService(
        _CaptureTransport(),
        ScreenshotConfig(retention_hours=1, max_width=2048, max_height=2048),
        publisher,
        workspaces=TemporaryWorkspaceService(temp_root=tmp_path / "os-temp"),
    )

    def fail(*_args, **_kwargs):
        raise OSError("publish failed")

    monkeypatch.setattr(artifacts, "publish_file_exact", fail)

    with pytest.raises(BridgeError) as caught:
        service.capture_viewport(_Session())

    assert caught.value.code == "screenshot_failed"
    capture_dir = artifacts.root / "capture"
    assert not capture_dir.exists() or list(capture_dir.iterdir()) == []


def test_capture_scripts_are_physically_separated_from_host_orchestration() -> None:
    import houbridge.capture.screenshot as host_module
    from houbridge.houdini.scripts.capture import screenshot, viewport, window

    host_source = Path(host_module.__file__).read_text(encoding="utf-8")
    assert "hou.qt.mainWindow" not in host_source
    assert "hou.geometryViewportLayout" not in host_source
    assert "runpy.run_path" in Path(screenshot.__file__).read_text(encoding="utf-8")
    assert "source_scene" in Path(viewport.__file__).read_text(encoding="utf-8")
    assert "hou.qt.mainWindow()" in Path(window.__file__).read_text(encoding="utf-8")


def test_capture_retention_cleanup_is_lazy_and_scoped_to_capture_namespace(tmp_path: Path) -> None:
    artifacts = TemporaryArtifactService(temp_root=tmp_path / "os-temp")
    capture_dir = artifacts.root / "capture"
    capture_dir.mkdir(parents=True, exist_ok=True)
    old = capture_dir / "viewport20260911-1800-001.png"
    old.write_bytes(b"old")
    unrelated = artifacts.publish_bytes(
        b"keep",
        namespace="resource",
        stem="resource",
        extension=".bin",
    )
    import os

    os.utime(old, (1_000.0, 1_000.0))
    os.utime(unrelated, (1_000.0, 1_000.0))
    publisher = CaptureArtifactPublisher(
        artifacts,
        1,
        now_timestamp=lambda: 5_000.0,
        now_datetime=lambda: datetime(2026, 9, 11, 19, 42),
    )

    publisher.cleanup_expired()

    assert not old.exists()
    assert unrelated.exists()
