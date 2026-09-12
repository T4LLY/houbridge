from __future__ import annotations

from typer.testing import CliRunner

from houbridge.cli.main import app


def test_root_help_exposes_implemented_session_family() -> None:
    result = CliRunner().invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "session" in result.stdout


def test_session_help_exposes_info_without_future_stub_commands() -> None:
    result = CliRunner().invoke(app, ["session", "--help"])

    assert result.exit_code == 0
    assert "info" in result.stdout
    assert "new" not in result.stdout
    assert "promote" not in result.stdout
