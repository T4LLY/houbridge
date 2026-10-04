from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from typer.testing import CliRunner

from houbridge.cli import capture_cmd
from houbridge.cli.main import app
from houbridge.houdini.transport import HoudiniTarget


runner = CliRunner()


class _Policy:
    def render(self, payload, *, allow_resource_fallback=True):
        del allow_resource_fallback
        from houbridge.output.json import serialize_public_json

        return serialize_public_json(payload)


class _Resolver:
    def __init__(self) -> None:
        self.calls = []

    def resolve(self, session):
        self.calls.append(session)
        return SimpleNamespace(target=HoudiniTarget("127.0.0.1", 49152))


class _TurntableService:
    def __init__(self) -> None:
        self.calls = []

    def capture(self, resolved, **kwargs):
        self.calls.append((resolved, kwargs))
        return {"path": "D:/Temp/turntable.mp4"}


class _CameraService:
    def __init__(self) -> None:
        self.calls = []

    def list(self, resolved):
        self.calls.append(("list", resolved, {}))
        return {"cameras": [{"path": "/obj/cam1", "type": "obj", "resolution": [1920, 1080]}]}

    def detail(self, resolved, camera_path):
        self.calls.append(("detail", resolved, {"camera_path": camera_path}))
        return {
            "path": camera_path,
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

    def capture(self, resolved, camera_path, **kwargs):
        self.calls.append(("capture", resolved, {"camera_path": camera_path, **kwargs}))
        return {"path": "D:/Temp/camera.png"}


class _ScreenshotService:
    def __init__(self) -> None:
        self.viewport_calls = []
        self.window_calls = []

    def capture_viewport(self, resolved, **kwargs):
        self.viewport_calls.append((resolved, kwargs))
        return {"path": "D:/Temp/viewport.png"}

    def capture_window(self, resolved, **kwargs):
        self.window_calls.append((resolved, kwargs))
        return {
            "path": "D:/Temp/window.png",
            "bounds": {
                "width": 10,
                "height": 10,
                "coordinate_space": "final_png_top_left",
                "source_width": 10,
                "source_height": 10,
                "scale_x": 1.0,
                "scale_y": 1.0,
                "areas": [],
            },
        }


class _ViewportInfo:
    def __init__(self, _transport) -> None:
        pass

    def info(self, _resolved):
        return {
            "panes": [
                {
                    "name": "panetab1",
                    "current_node": "/obj/geo1/OUT",
                    "viewports": [
                        {
                            "name": "persp1",
                            "type": "persp",
                            "width": 10,
                            "height": 10,
                        }
                    ],
                }
            ]
        }


def _install(monkeypatch):
    settings = SimpleNamespace()
    resolver = _Resolver()
    transport = object()
    service = _ScreenshotService()
    turntable = _TurntableService()
    camera = _CameraService()
    monkeypatch.setattr(capture_cmd, "load_config", lambda: settings)
    monkeypatch.setattr(capture_cmd, "_resolver_and_transport", lambda _settings: (resolver, transport))
    monkeypatch.setattr(capture_cmd, "_screenshot_service", lambda _settings, _transport: service)
    monkeypatch.setattr(capture_cmd, "_turntable_service", lambda _settings, _transport: turntable)
    monkeypatch.setattr(capture_cmd, "_camera_service", lambda _settings, _transport: camera)
    monkeypatch.setattr(capture_cmd, "ViewportInfoService", _ViewportInfo)
    monkeypatch.setattr(capture_cmd.OutputPolicy, "from_config", lambda _settings: _Policy())
    return resolver, service, turntable


def test_capture_services_propagate_configured_sequence_lock_timeout() -> None:
    timeout = 0.37
    settings = SimpleNamespace(
        storage=SimpleNamespace(data_dir=Path("D:/Temp/houbridge-test")),
        houdini=SimpleNamespace(lock_timeout_seconds=timeout),
        screenshot=SimpleNamespace(retention_hours=24),
    )

    services = (
        capture_cmd._screenshot_service(settings, object()),
        capture_cmd._turntable_service(settings, object()),
        capture_cmd._camera_service(settings, object()),
    )

    assert [
        service._publisher._sequences.lock_timeout_seconds for service in services
    ] == [
        timeout,
        timeout,
        timeout,
    ]


def test_capture_help_exposes_phase26_commands_and_current_options() -> None:
    root = runner.invoke(app, ["--help"])
    capture = runner.invoke(app, ["capture", "--help"])
    panes = runner.invoke(app, ["capture", "panes", "--help"])
    viewport = runner.invoke(app, ["capture", "viewport", "--help"])
    window = runner.invoke(app, ["capture", "window", "--help"])
    turntable = runner.invoke(app, ["capture", "turntable", "--help"])
    camera = runner.invoke(app, ["capture", "camera", "--help"])

    assert (
        root.exit_code
        == capture.exit_code
        == panes.exit_code
        == viewport.exit_code
        == window.exit_code
        == turntable.exit_code
        == camera.exit_code
        == 0
    )
    assert "capture" in root.stdout
    assert "panes" in capture.stdout
    assert "viewport" in capture.stdout
    assert "window" in capture.stdout
    assert "ocr" not in capture.stdout
    assert "turntable" in capture.stdout
    assert "camera" in capture.stdout
    assert "--session" in panes.stdout
    for option in (
        "--info", "--top", "--bottom", "--front", "--back", "--left", "--right",
        "--persp", "--uv", "--scale", "--preset", "--pane", "--pass",
        "--model", "--unit", "--curvature-scale", "--curvature-colormap", "--session",
    ):
        assert option in viewport.stdout
    assert "--quad" not in viewport.stdout
    for option in ("--scale", "--crop", "--preset", "--session"):
        assert option in window.stdout
    for option in (
        "--frames", "--fps", "--scale", "--pivot", "--distance", "--preset",
        "--pane", "--session",
    ):
        assert option in turntable.stdout
    assert "--ffmpeg" not in turntable.stdout
    assert "CAMERA_PATH" in camera.stdout
    for option in ("--list", "--detail", "--scale", "--pane", "--session"):
        assert option in camera.stdout
    for output in (viewport.stdout, window.stdout, turntable.stdout, camera.stdout):
        for forbidden in ("--root", "--port", "--hcommand"):
            assert forbidden not in output


def test_capture_panes_uses_selected_session_and_viewport_info_shape(monkeypatch) -> None:
    resolver, _service, _turntable = _install(monkeypatch)

    result = runner.invoke(app, ["capture", "panes", "--session", "4"])

    assert result.exit_code == 0
    assert result.stdout == (
        '{"panes":[{"name":"panetab1","current_node":"/obj/geo1/OUT",'
        '"viewports":[{"name":"persp1","type":"persp","width":10,"height":10}]}]}\n'
    )
    assert resolver.calls == [4]


def test_viewport_info_uses_selected_session_and_exact_public_shape(monkeypatch) -> None:
    resolver, _service, _turntable = _install(monkeypatch)

    result = runner.invoke(app, ["capture", "viewport", "--info", "--session", "3"])

    assert result.exit_code == 0
    assert result.stdout == (
        '{"panes":[{"name":"panetab1","current_node":"/obj/geo1/OUT",'
        '"viewports":[{"name":"persp1","type":"persp","width":10,"height":10}]}]}\n'
    )
    assert resolver.calls == [3]


def test_viewport_capture_passes_multiple_directions_and_scale(monkeypatch) -> None:
    _resolver, service, _turntable = _install(monkeypatch)

    result = runner.invoke(
        app,
        [
            "capture", "viewport", "--front", "--right", "--scale", "2.5",
            "--pane", "panetab4", "--session", "2",
        ],
    )

    assert result.exit_code == 0
    assert result.stdout == '{"path":"D:/Temp/viewport.png"}\n'
    assert service.viewport_calls[0][1] == {
        "views": ("front", "right"),
        "scale": 2.5,
        "preset_path": None,
        "pane": "panetab4",
    }


def test_viewport_info_conflict_uses_spec_code() -> None:
    info = runner.invoke(app, ["capture", "viewport", "--info", "--scale", "2"])
    pane = runner.invoke(app, ["capture", "viewport", "--info", "--pane", "panetab1"])

    assert info.exit_code == 1
    assert '"code":"capture_info_conflict"' in info.stdout
    assert pane.exit_code == 1
    assert '"code":"capture_info_conflict"' in pane.stdout


def test_window_command_passes_explicit_crop_and_returns_inline_bounds(monkeypatch) -> None:
    _resolver, service, _turntable = _install(monkeypatch)

    result = runner.invoke(
        app,
        ["capture", "window", "--scale", "0.5", "--crop", "network_editor", "--session", "4"],
    )

    assert result.exit_code == 0
    assert '"path":"D:/Temp/window.png"' in result.stdout
    assert '"bounds":{' in result.stdout
    assert service.window_calls[0][1] == {
        "scale": 0.5,
        "crop": "network_editor",
        "preset_path": None,
    }


def test_capture_ocr_command_is_not_exposed() -> None:
    result = runner.invoke(app, ["capture", "ocr", "image.png"])

    assert result.exit_code == 2


def test_turntable_command_uses_defaults_explicit_options_session_and_common_output(monkeypatch) -> None:
    resolver, _screenshot, service = _install(monkeypatch)

    default_result = runner.invoke(app, ["capture", "turntable"])
    assert default_result.exit_code == 0
    assert service.calls[0][1]["frames"] == 160
    assert service.calls[0][1]["fps"] == 30
    assert service.calls[0][1]["distance"] is None

    result = runner.invoke(
        app,
        [
            "capture", "turntable",
            "--frames", "8",
            "--fps", "24",
            "--scale", "0.5",
            "--pivot", "1,2,3",
            "--distance", "5",
            "--pane", "panetab4",
            "--session", "6",
        ],
    )

    assert result.exit_code == 0
    assert result.stdout == '{"path":"D:/Temp/turntable.mp4"}\n'
    assert resolver.calls == [None, 6]
    assert service.calls[1][1] == {
        "frames": 8,
        "fps": 24,
        "scale": 0.5,
        "pivot": (1.0, 2.0, 3.0),
        "distance": 5.0,
        "preset_path": None,
        "pane": "panetab4",
    }


def test_turntable_invalid_pivot_fails_before_session_resolution(monkeypatch) -> None:
    resolver, _screenshot, _service = _install(monkeypatch)

    result = runner.invoke(app, ["capture", "turntable", "--pivot", "1,2"])

    assert result.exit_code == 1
    assert '"code":"invalid_turntable_pivot"' in result.stdout
    assert resolver.calls == []


def test_camera_command_list_detail_and_capture_modes(monkeypatch) -> None:
    resolver, _screenshot, _turntable = _install(monkeypatch)
    camera = _CameraService()
    monkeypatch.setattr(capture_cmd, "_camera_service", lambda _settings, _transport: camera)

    listed = runner.invoke(app, ["capture", "camera", "--list", "--session", "2"])
    detailed = runner.invoke(app, ["capture", "camera", "/obj/cam1", "--detail"])
    captured = runner.invoke(
        app,
        ["capture", "camera", "/obj/cam1", "--scale", "0.5", "--pane", "panetab4"],
    )

    assert listed.exit_code == detailed.exit_code == captured.exit_code == 0
    assert listed.stdout == '{"cameras":[{"path":"/obj/cam1","type":"obj","resolution":[1920,1080]}]}\n'
    assert '"projection":"perspective"' in detailed.stdout
    assert captured.stdout == '{"path":"D:/Temp/camera.png"}\n'
    assert resolver.calls == [2, None, None]
    assert camera.calls[0][0] == "list"
    assert camera.calls[1][0] == "detail"
    assert camera.calls[1][2] == {"camera_path": "/obj/cam1"}
    assert camera.calls[2][0] == "capture"
    assert camera.calls[2][2] == {
        "camera_path": "/obj/cam1",
        "scale": 0.5,
        "pane": "panetab4",
    }


def test_camera_command_requires_path_unless_list_and_rejects_mode_conflicts(monkeypatch) -> None:
    resolver, _screenshot, _turntable = _install(monkeypatch)

    missing = runner.invoke(app, ["capture", "camera"])
    detail_missing = runner.invoke(app, ["capture", "camera", "--detail"])
    list_path = runner.invoke(app, ["capture", "camera", "/obj/cam1", "--list"])
    detail_scale = runner.invoke(app, ["capture", "camera", "/obj/cam1", "--detail", "--scale", "2"])

    assert missing.exit_code == detail_missing.exit_code == list_path.exit_code == detail_scale.exit_code == 1
    assert '"code":"camera_path_required"' in missing.stdout
    assert '"code":"camera_path_required"' in detail_missing.stdout
    assert '"code":"capture_camera_list_conflict"' in list_path.stdout
    assert '"code":"capture_camera_detail_conflict"' in detail_scale.stdout
    assert resolver.calls == []


def test_viewport_analysis_options_build_shared_request(monkeypatch) -> None:
    _resolver, service, _turntable = _install(monkeypatch)

    result = runner.invoke(
        app,
        [
            "capture", "viewport", "--front", "--pass", "grid",
            "--unit", "0.5", "--model", "/obj/a", "--model", "/obj/b",
            "--pane", "panetab4",
        ],
    )

    assert result.exit_code == 0
    kwargs = service.viewport_calls[0][1]
    assert kwargs["views"] == ("front",)
    assert kwargs["pane"] == "panetab4"
    analysis = kwargs["analysis"]
    assert analysis.capture_pass == "grid"
    assert analysis.grid_unit == 0.5
    assert analysis.model_paths == ("/obj/a", "/obj/b")


def test_viewport_analysis_info_conflicts_before_session_resolution(monkeypatch) -> None:
    _resolver, _service, _turntable = _install(monkeypatch)

    result = runner.invoke(app, ["capture", "viewport", "--info", "--pass", "depth"])

    assert result.exit_code == 1
    assert '"code":"capture_info_conflict"' in result.stdout


def test_viewport_grid_without_unit_uses_spec_error(monkeypatch) -> None:
    _resolver, _service, _turntable = _install(monkeypatch)

    result = runner.invoke(app, ["capture", "viewport", "--pass", "grid"])

    assert result.exit_code == 1
    assert '"code":"grid_unit_required"' in result.stdout


def test_camera_analysis_options_build_shared_request(monkeypatch) -> None:
    resolver, _screenshot, _turntable = _install(monkeypatch)
    camera = _CameraService()
    monkeypatch.setattr(capture_cmd, "_camera_service", lambda _settings, _transport: camera)

    result = runner.invoke(
        app,
        [
            "capture", "camera", "/obj/cam1", "--pass", "grid",
            "--unit", "0.5", "--model", "/obj/a", "--model", "/obj/b",
            "--scale", "0.5", "--pane", "panetab4",
        ],
    )

    assert result.exit_code == 0
    assert resolver.calls == [None]
    kwargs = camera.calls[0][2]
    assert kwargs["camera_path"] == "/obj/cam1"
    assert kwargs["scale"] == 0.5
    assert kwargs["pane"] == "panetab4"
    analysis = kwargs["analysis"]
    assert analysis.capture_pass == "grid"
    assert analysis.grid_unit == 0.5
    assert analysis.model_paths == ("/obj/a", "/obj/b")


def test_camera_analysis_options_conflict_with_list_and_detail(monkeypatch) -> None:
    resolver, _screenshot, _turntable = _install(monkeypatch)

    listed = runner.invoke(app, ["capture", "camera", "--list", "--pass", "depth"])
    detailed = runner.invoke(
        app,
        ["capture", "camera", "/obj/cam1", "--detail", "--model", "/obj/a", "--pass", "depth"],
    )

    assert listed.exit_code == detailed.exit_code == 1
    assert '"code":"capture_camera_list_conflict"' in listed.stdout
    assert '"code":"capture_camera_detail_conflict"' in detailed.stdout
    assert resolver.calls == []


def test_camera_grid_without_unit_uses_spec_error(monkeypatch) -> None:
    resolver, _screenshot, _turntable = _install(monkeypatch)
    camera = _CameraService()
    monkeypatch.setattr(capture_cmd, "_camera_service", lambda _settings, _transport: camera)

    result = runner.invoke(app, ["capture", "camera", "/obj/cam1", "--pass", "grid"])

    assert result.exit_code == 1
    assert '"code":"grid_unit_required"' in result.stdout
    assert resolver.calls == []
    assert camera.calls == []


def test_viewport_curvature_options_build_shared_request(monkeypatch) -> None:
    _resolver, service, _turntable = _install(monkeypatch)

    result = runner.invoke(
        app,
        [
            "capture", "viewport", "--pass", "curvature",
            "--curvature-scale", "2", "--curvature-colormap", "gray",
            "--model", "/obj/a",
        ],
    )

    assert result.exit_code == 0
    analysis = service.viewport_calls[0][1]["analysis"]
    assert analysis.capture_pass == "curvature"
    assert analysis.curvature_scale == 2.0
    assert analysis.curvature_colormap == "gray"
    assert analysis.model_paths == ("/obj/a",)


def test_camera_curvature_options_build_shared_request(monkeypatch) -> None:
    resolver, _screenshot, _turntable = _install(monkeypatch)
    camera = _CameraService()
    monkeypatch.setattr(capture_cmd, "_camera_service", lambda _settings, _transport: camera)

    result = runner.invoke(
        app,
        [
            "capture", "camera", "/obj/cam1", "--pass", "curvature",
            "--curvature-scale", "0.5", "--curvature-colormap", "rg",
            "--model", "/obj/a",
        ],
    )

    assert result.exit_code == 0
    assert resolver.calls == [None]
    analysis = camera.calls[0][2]["analysis"]
    assert analysis.capture_pass == "curvature"
    assert analysis.curvature_scale == 0.5
    assert analysis.curvature_colormap == "rg"
    assert analysis.model_paths == ("/obj/a",)
