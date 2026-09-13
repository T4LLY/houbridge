from __future__ import annotations

from types import SimpleNamespace

from typer.testing import CliRunner

from houbridge.cli import common, resource_cmd
from houbridge.cli.main import app
from houbridge.errors import BridgeError


runner = CliRunner()


class _Reader:
    def info(self, resource_id: str):
        return {"mime": "text/plain", "tokens": 2}

    def get(self, resource_id: str, *, full: bool = False):
        return {"truncated": False, "result": "hello"}

    def slice(self, resource_id: str, *, offset: int, limit: int):
        if offset < 0:
            raise BridgeError("invalid_slice", "offset must be >= 0.")
        return {"result": "ell"}

    def search(self, resource_id: str, query: str, *, offset: int = 0):
        return {"hit_count": 1, "hits": [{"offset": 0}]}


class _Dumper:
    def dump(self, resource_id: str):
        return {"path": "/tmp/houbridge/artifacts/resource/resource-test.txt"}


def _install_services(monkeypatch) -> None:
    monkeypatch.setattr(resource_cmd, "_reader", lambda: _Reader())
    monkeypatch.setattr(resource_cmd, "_dumper", lambda: _Dumper())
    monkeypatch.setattr(
        common,
        "load_config",
        lambda: SimpleNamespace(output=SimpleNamespace(inline_max_tokens=4096)),
    )


def test_root_help_exposes_resource_family() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "resource" in result.stdout


def test_resource_help_exposes_only_current_inspection_commands() -> None:
    result = runner.invoke(app, ["resource", "--help"])

    assert result.exit_code == 0
    for command in ("info", "get", "slice", "search", "dump"):
        assert command in result.stdout


def test_resource_get_uses_full_flag_not_legacy_allow_full(monkeypatch) -> None:
    _install_services(monkeypatch)
    help_result = runner.invoke(app, ["resource", "get", "--help"])
    result = runner.invoke(app, ["resource", "get", "abc", "--full"])

    assert "--full" in help_result.stdout
    assert "--allow-full" not in help_result.stdout
    assert result.exit_code == 0
    assert result.stdout == '{"truncated":false,"result":"hello"}\n'


def test_resource_commands_emit_exact_public_shapes(monkeypatch) -> None:
    _install_services(monkeypatch)

    info = runner.invoke(app, ["resource", "info", "abc"])
    sliced = runner.invoke(
        app,
        ["resource", "slice", "abc", "--offset", "1", "--limit", "3"],
    )
    searched = runner.invoke(app, ["resource", "search", "abc", "hello"])
    dumped = runner.invoke(app, ["resource", "dump", "abc"])

    assert info.stdout == '{"mime":"text/plain","tokens":2}\n'
    assert sliced.stdout == '{"result":"ell"}\n'
    assert searched.stdout == '{"hit_count":1,"hits":[{"offset":0}]}\n'
    assert dumped.stdout == '{"path":"/tmp/houbridge/artifacts/resource/resource-test.txt"}\n'


def test_resource_validation_failure_uses_shared_error_envelope(monkeypatch) -> None:
    _install_services(monkeypatch)

    result = runner.invoke(
        app,
        ["resource", "slice", "abc", "--offset", "-1", "--limit", "1"],
    )

    assert result.exit_code == 1
    assert result.stdout == (
        '{"error":true,"code":"invalid_slice","message":"offset must be >= 0."}\n'
    )


def test_resource_surface_exposes_no_storage_override(monkeypatch) -> None:
    _install_services(monkeypatch)

    for command in ("info", "get", "slice", "search", "dump"):
        result = runner.invoke(app, ["resource", command, "--help"])
        assert "--root" not in result.stdout
