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
    monkeypatch.setattr(capture_cmd, "load_config", lambda: settings)
    monkeypatch.setattr(capture_cmd, "_resolver_and_transport", lambda _settings: (resolver, transport))
    monkeypatch.setattr(capture_cmd, "_screenshot_service", lambda _settings, _transport: service)
    monkeypatch.setattr(capture_cmd, "ViewportInfoService", _ViewportInfo)
    monkeypatch.setattr(capture_cmd.OutputPolicy, "from_config", lambda _settings: _Policy())
    return resolver, service


def test_capture_help_exposes_only_phase24_commands_and_current_options() -> None:
    root = runner.invoke(app, ["--help"])
    capture = runner.invoke(app, ["capture", "--help"])
    viewport = runner.invoke(app, ["capture", "viewport", "--help"])
    window = runner.invoke(app, ["capture", "window", "--help"])

    assert root.exit_code == capture.exit_code == viewport.exit_code == window.exit_code == 0
    assert "capture" in root.stdout
    assert "viewport" in capture.stdout
    assert "window" in capture.stdout
    assert "ocr" not in capture.stdout
    assert "turntable" not in capture.stdout
    for option in (
        "--info", "--top", "--bottom", "--front", "--back", "--left", "--right",
        "--persp", "--uv", "--quad", "--scale", "--preset", "--session",
    ):
        assert option in viewport.stdout
    for option in ("--scale", "--crop", "--preset", "--session"):
        assert option in window.stdout
    for output in (viewport.stdout, window.stdout):
        for forbidden in ("--root", "--port", "--hcommand"):
            assert forbidden not in output


def test_viewport_info_uses_selected_session_and_exact_public_shape(monkeypatch) -> None:
    resolver, _service = _install(monkeypatch)

    result = runner.invoke(app, ["capture", "viewport", "--info", "--session", "3"])

    assert result.exit_code == 0
    assert result.stdout == '{"viewports":[{"name":"persp1","type":"persp","width":10,"height":10}]}\n'
    assert resolver.calls == [3]


def test_viewport_capture_passes_multiple_directions_and_scale(monkeypatch) -> None:
    _resolver, service = _install(monkeypatch)

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
    _resolver, service = _install(monkeypatch)

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
