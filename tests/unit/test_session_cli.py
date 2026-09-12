from __future__ import annotations

from typer.testing import CliRunner

from houbridge.cli.main import app


def test_root_help_exposes_implemented_session_family() -> None:
    result = CliRunner().invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "session" in result.stdout


def test_session_help_exposes_info_and_new_without_future_promote_stub() -> None:
    result = CliRunner().invoke(app, ["session", "--help"])

    assert result.exit_code == 0
    assert "info" in result.stdout
    assert "new" in result.stdout
    assert "promote" not in result.stdout


def test_session_new_help_exposes_only_current_options() -> None:
    result = CliRunner().invoke(app, ["session", "new", "--help"])

    assert result.exit_code == 0
    assert "--file" in result.stdout
    assert "--headless" in result.stdout
    assert "--hcommand" in result.stdout
    assert "--port" not in result.stdout


def test_session_new_emits_exact_public_success_shape(monkeypatch, tmp_path) -> None:
    from types import SimpleNamespace

    from houbridge.cli import session_cmd

    monkeypatch.setattr(
        session_cmd,
        "load_config",
        lambda: SimpleNamespace(
            storage=SimpleNamespace(data_dir=tmp_path),
            houdini=SimpleNamespace(transport_timeout_seconds=120.0),
        ),
    )
    monkeypatch.setattr(
        session_cmd.SessionNewService,
        "create",
        lambda self, **kwargs: {"session": 2, "port": 49153, "pid": 18744},
    )

    result = CliRunner().invoke(app, ["session", "new", "--headless"])

    assert result.exit_code == 0
    assert result.stdout == '{"session":2,"port":49153,"pid":18744}\n'
