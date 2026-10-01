from __future__ import annotations

from types import SimpleNamespace

from typer.testing import CliRunner

from houbridge.cli import hip_cmd
from houbridge.cli.main import app


runner = CliRunner()


class _Policy:
    def render(self, payload, *, allow_resource_fallback=True):
        del allow_resource_fallback
        from houbridge.output.json import serialize_public_json

        return serialize_public_json(payload)


class _Resolver:
    def __init__(self) -> None:
        self.calls: list[int | None] = []

    def resolve(self, session):
        self.calls.append(session)
        return object()


class _Service:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def info(self, resolved):
        self.calls.append(("info", resolved))
        return {"path": "C:/project/scene.hip", "dirty": True, "new": False}

    def save(self, resolved):
        self.calls.append(("save", resolved))
        return {"path": "C:/project/scene.hip", "status": "saved"}


def _install(monkeypatch):
    settings = SimpleNamespace()
    service = _Service()
    resolver = _Resolver()
    monkeypatch.setattr(hip_cmd, "load_config", lambda: settings)
    monkeypatch.setattr(
        hip_cmd, "_service_and_resolver", lambda _settings: (service, resolver)
    )
    monkeypatch.setattr(hip_cmd.OutputPolicy, "from_config", lambda _settings: _Policy())
    return service, resolver


def test_hip_help_exposes_only_info_and_save() -> None:
    result = runner.invoke(app, ["hip", "--help"])

    assert result.exit_code == 0
    assert "info" in result.stdout
    assert "save" in result.stdout
    assert "load" not in result.stdout
    assert "backup" not in result.stdout


def test_hip_info_targets_selected_session_and_emits_exact_shape(monkeypatch) -> None:
    service, resolver = _install(monkeypatch)

    result = runner.invoke(app, ["hip", "info", "--session", "3"])

    assert result.exit_code == 0
    assert result.stdout == (
        '{"path":"C:/project/scene.hip","dirty":true,"new":false}\n'
    )
    assert resolver.calls == [3]
    assert service.calls[0][0] == "info"


def test_hip_save_uses_primary_by_default_and_emits_status(monkeypatch) -> None:
    service, resolver = _install(monkeypatch)

    result = runner.invoke(app, ["hip", "save"])

    assert result.exit_code == 0
    assert result.stdout == '{"path":"C:/project/scene.hip","status":"saved"}\n'
    assert resolver.calls == [None]
    assert service.calls[0][0] == "save"


def test_hip_commands_expose_only_session_target_option() -> None:
    for command in ("info", "save"):
        result = runner.invoke(app, ["hip", command, "--help"])
        assert result.exit_code == 0
        assert "--session" in result.stdout
        for forbidden in ("--file", "--path", "--port", "--hcommand"):
            assert forbidden not in result.stdout
