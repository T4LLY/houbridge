from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

from houbridge.houdini.scripts.capture.analysis_runtime import flipbook_analysis


class _Settings:
    def stash(self):
        return self

    def frameRange(self, value):
        self.frame_range = value

    def outputToMPlay(self, value):
        self.output_to_mplay = value

    def output(self, value):
        self.output_path = value

    def useResolution(self, value):
        self.use_resolution = value

    def resolution(self, value):
        self.output_resolution = value

    def outputZoom(self, value):
        self.output_zoom = value

    def cropOutMaskOverlay(self, value):
        self.crop_camera = value


class _Scene:
    def __init__(self, output_path: Path) -> None:
        self.settings = _Settings()
        self.output_path = output_path
        self.environ = {}

    def flipbookSettings(self):
        return self.settings

    def flipbook(self, _viewport, _settings) -> None:
        self.environ = {
            key: os.environ.get(key)
            for key in (
                "HOUBRIDGE_CAPTURE_CURVATURE_SCALE",
                "HOUBRIDGE_CAPTURE_CURVATURE_COLORMAP",
            )
        }
        self.output_path.write_bytes(b"png")


def test_flipbook_analysis_publishes_curvature_environment_only_during_capture(tmp_path: Path) -> None:
    output = tmp_path / "curvature.png"
    trigger = tmp_path / "trigger.png"
    scene = _Scene(output)
    hou = SimpleNamespace(frame=lambda: 12)

    os.environ.pop("HOUBRIDGE_CAPTURE_CURVATURE_SCALE", None)
    os.environ.pop("HOUBRIDGE_CAPTURE_CURVATURE_COLORMAP", None)
    flipbook_analysis(
        scene,
        object(),
        output_path=output,
        trigger_path=trigger,
        generation="abc123",
        capture_pass="curvature",
        model_paths=("/obj/a",),
        grid_unit=None,
        curvature_scale=2.0,
        curvature_colormap="gray",
        resolution=(640, 360),
        crop_camera=False,
        hou=hou,
    )

    assert scene.environ == {
        "HOUBRIDGE_CAPTURE_CURVATURE_SCALE": "2",
        "HOUBRIDGE_CAPTURE_CURVATURE_COLORMAP": "gray",
    }
    assert "HOUBRIDGE_CAPTURE_CURVATURE_SCALE" not in os.environ
    assert "HOUBRIDGE_CAPTURE_CURVATURE_COLORMAP" not in os.environ


def test_camera_flipbook_resolution_plan_matches_beauty_tiny_resolution_contract() -> None:
    from houbridge.houdini.scripts.capture.analysis_runtime import camera_flipbook_resolution_plan

    assert camera_flipbook_resolution_plan((640, 360)) == ((640, 360), 1.0)
    assert camera_flipbook_resolution_plan((1, 100)) == ((2, 200), 0.5)
    assert camera_flipbook_resolution_plan((100, 1)) == ((200, 2), 0.5)


class _Rop:
    def __init__(self, output_path: Path) -> None:
        self.output_path = output_path
        self.calls = []
        self.environ = {}

    def render(self, **kwargs) -> None:
        self.calls.append(kwargs)
        self.environ = {
            key: os.environ.get(key)
            for key in (
                "HOUBRIDGE_CAPTURE_ANALYSIS_PASS",
                "HOUBRIDGE_CAPTURE_ANALYSIS_MODELS",
            )
        }
        self.output_path.write_bytes(b"png")


def test_flipbook_analysis_rop_reuses_analysis_environment_for_headless(tmp_path: Path) -> None:
    from houbridge.houdini.scripts.capture.analysis_runtime import flipbook_analysis_rop

    output = tmp_path / "normal.png"
    trigger = tmp_path / "trigger.png"
    rop = _Rop(output)
    hou = SimpleNamespace(frame=lambda: 7)

    flipbook_analysis_rop(
        rop,
        output_path=output,
        trigger_path=trigger,
        generation="abc123",
        capture_pass="normal",
        model_paths=("/obj/a", "/obj/b"),
        grid_unit=None,
        curvature_scale=1.0,
        curvature_colormap="rg",
        hou=hou,
    )

    assert rop.calls == [
        {
            "frame_range": (7, 7),
            "output_file": str(trigger),
            "ignore_inputs": True,
            "verbose": True,
            "output_progress": True,
        }
    ]
    assert rop.environ == {
        "HOUBRIDGE_CAPTURE_ANALYSIS_PASS": "normal",
        "HOUBRIDGE_CAPTURE_ANALYSIS_MODELS": "/obj/a;/obj/b",
    }
    assert "HOUBRIDGE_CAPTURE_ANALYSIS_PASS" not in os.environ
    assert "HOUBRIDGE_CAPTURE_ANALYSIS_MODELS" not in os.environ
