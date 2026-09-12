from __future__ import annotations

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
        return {"viewports": [{"name": "persp1", "type": "persp", "width": 10, "height": 10}]}


def _install(monkeypatch):
    settings = SimpleNamespace()
    resolver = _Resolver()
    transport = object()
    service = _ScreenshotService()
    turntable = _TurntableService()
    monkeypatch.setattr(capture_cmd, "load_config", lambda: settings)
    monkeypatch.setattr(capture_cmd, "_resolver_and_transport", lambda _settings: (resolver, transport))
    monkeypatch.setattr(capture_cmd, "_screenshot_service", lambda _settings, _transport: service)
    monkeypatch.setattr(capture_cmd, "_turntable_service", lambda _settings, _transport: turntable)
    monkeypatch.setattr(capture_cmd, "ViewportInfoService", _ViewportInfo)
    monkeypatch.setattr(capture_cmd.OutputPolicy, "from_config", lambda _settings: _Policy())
    return resolver, service, turntable


def test_capture_help_exposes_phase26_commands_and_current_options() -> None:
    root = runner.invoke(app, ["--help"])
    capture = runner.invoke(app, ["capture", "--help"])
    viewport = runner.invoke(app, ["capture", "viewport", "--help"])
    window = runner.invoke(app, ["capture", "window", "--help"])
    turntable = runner.invoke(app, ["capture", "turntable", "--help"])

    assert (
        root.exit_code
        == capture.exit_code
        == viewport.exit_code
        == window.exit_code
        == turntable.exit_code
        == 0
    )
    assert "capture" in root.stdout
    assert "viewport" in capture.stdout
    assert "window" in capture.stdout
    assert "ocr" in capture.stdout
    assert "turntable" in capture.stdout
    for option in (
        "--info", "--top", "--bottom", "--front", "--back", "--left", "--right",
        "--persp", "--uv", "--quad", "--scale", "--preset", "--session",
    ):
        assert option in viewport.stdout
    for option in ("--scale", "--crop", "--preset", "--session"):
        assert option in window.stdout
    for option in ("--frames", "--fps", "--scale", "--pivot", "--distance", "--preset", "--session"):
        assert option in turntable.stdout
    assert "--ffmpeg" not in turntable.stdout
    for output in (viewport.stdout, window.stdout, turntable.stdout):
        for forbidden in ("--root", "--port", "--hcommand"):
            assert forbidden not in output


def test_viewport_info_uses_selected_session_and_exact_public_shape(monkeypatch) -> None:
    resolver, _service, _turntable = _install(monkeypatch)

    result = runner.invoke(app, ["capture", "viewport", "--info", "--session", "3"])

    assert result.exit_code == 0
    assert result.stdout == '{"viewports":[{"name":"persp1","type":"persp","width":10,"height":10}]}\n'
    assert resolver.calls == [3]


def test_viewport_capture_passes_multiple_directions_and_scale(monkeypatch) -> None:
    _resolver, service, _turntable = _install(monkeypatch)

    result = runner.invoke(
        app,
        ["capture", "viewport", "--front", "--right", "--scale", "2.5", "--session", "2"],
    )

    assert result.exit_code == 0
    assert result.stdout == '{"path":"D:/Temp/viewport.png"}\n'
    assert service.viewport_calls[0][1] == {
        "views": ("front", "right"),
        "quad": False,
        "scale": 2.5,
        "preset_path": None,
    }


def test_viewport_info_conflict_and_quad_conflict_use_spec_codes() -> None:
    info = runner.invoke(app, ["capture", "viewport", "--info", "--scale", "2"])
    quad = runner.invoke(app, ["capture", "viewport", "--quad", "--front"])

    assert info.exit_code == 1
    assert '"code":"capture_info_conflict"' in info.stdout
    assert quad.exit_code == 1
    assert '"code":"screenshot_view_conflict"' in quad.stdout


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


def test_ocr_command_uses_required_image_and_common_output_policy(monkeypatch, tmp_path) -> None:
    image = tmp_path / "window.png"
    image.write_bytes(b"image")
    logical = {"ocr": {"File": [{"score": 0.99, "bbox": [1, 2, 100, 20]}]}}
    recognized = []

    class _OCRService:
        def recognize(self, received):
            recognized.append(received)
            return logical

    class _OCRPolicy:
        def render(self, payload, *, allow_resource_fallback=True):
            assert payload is logical
            assert allow_resource_fallback is True
            return '{"resource":"ocr-output-000"}'

    monkeypatch.setattr(capture_cmd, "load_config", lambda: SimpleNamespace())
    monkeypatch.setattr(capture_cmd, "ScreenshotOCRService", _OCRService)
    monkeypatch.setattr(capture_cmd.OutputPolicy, "from_config", lambda _settings: _OCRPolicy())

    result = runner.invoke(app, ["capture", "ocr", str(image)])

    assert result.exit_code == 0
    assert result.stdout == '{"resource":"ocr-output-000"}\n'
    assert recognized == [image]


def test_ocr_command_missing_image_uses_spec_error_after_dispatch(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(capture_cmd, "load_config", lambda: SimpleNamespace())

    missing = tmp_path / "missing.png"
    result = runner.invoke(app, ["capture", "ocr", str(missing)])

    assert result.exit_code == 1
    assert '"code":"ocr_image_not_found"' in result.stdout

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
    }


def test_turntable_invalid_pivot_fails_before_session_resolution(monkeypatch) -> None:
    resolver, _screenshot, _service = _install(monkeypatch)

    result = runner.invoke(app, ["capture", "turntable", "--pivot", "1,2"])

    assert result.exit_code == 1
    assert '"code":"invalid_turntable_pivot"' in result.stdout
    assert resolver.calls == []
