from __future__ import annotations

from types import SimpleNamespace

from typer.testing import CliRunner

from houbridge.cli import search_cmd
from houbridge.cli.main import app
from houbridge.errors import BridgeError
from houbridge.formatting import CanonicalJsonNumber


runner = CliRunner()


class _Service:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def search(self, query: str, *, top_k: int = 10):
        self.calls.append((query, top_k))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class _Policy:
    def render(self, payload, *, allow_resource_fallback=True):
        del allow_resource_fallback
        from houbridge.output.json import serialize_public_json

        return serialize_public_json(payload)


def _install(monkeypatch, service: _Service) -> None:
    settings = SimpleNamespace()
    monkeypatch.setattr(search_cmd, "load_config", lambda: settings)
    monkeypatch.setattr(search_cmd, "_script_service", lambda _settings: service)
    monkeypatch.setattr(search_cmd.OutputPolicy, "from_config", lambda _settings: _Policy())


def test_root_help_exposes_search_and_phase21_exposes_only_script_subcommand() -> None:
    root = runner.invoke(app, ["--help"])
    search = runner.invoke(app, ["search", "--help"])

    assert root.exit_code == 0
    assert "search" in root.stdout
    assert search.exit_code == 0
    assert "script" in search.stdout
    for future_command in ("python", "vex", "node"):
        assert future_command not in search.stdout


def test_search_script_emits_exact_minimal_hit_shape(monkeypatch) -> None:
    service = _Service(
        {
            "hits": [
                {
                    "path": ".houbridge/python/build.py",
                    "score": CanonicalJsonNumber("301.278910"),
                    "description": "Builds geometry.",
                }
            ]
        }
    )
    _install(monkeypatch, service)

    result = runner.invoke(app, ["search", "script", "geometry", "--top-k", "7"])

    assert result.exit_code == 0
    assert result.stdout == (
        '{"hits":[{"path":".houbridge/python/build.py",'
        '"score":301.278910,"description":"Builds geometry."}]}\n'
    )
    assert service.calls == [("geometry", 7)]


def test_search_script_omits_description_and_returns_only_hits(monkeypatch) -> None:
    service = _Service(
        {
            "hits": [
                {
                    "path": ".houbridge/python/legacy.py",
                    "score": CanonicalJsonNumber("750.000000"),
                }
            ]
        }
    )
    _install(monkeypatch, service)

    result = runner.invoke(app, ["search", "script", "legacy"])

    assert result.exit_code == 0
    assert result.stdout == (
        '{"hits":[{"path":".houbridge/python/legacy.py","score":750.000000}]}\n'
    )


def test_search_script_top_k_contract_is_framework_validated() -> None:
    help_result = runner.invoke(app, ["search", "script", "--help"])
    low = runner.invoke(app, ["search", "script", "query", "--top-k", "0"])
    high = runner.invoke(app, ["search", "script", "query", "--top-k", "51"])

    assert help_result.exit_code == 0
    assert "--top-k" in help_result.stdout
    assert "--count" not in help_result.stdout
    assert low.exit_code == 2
    assert high.exit_code == 2


def test_search_script_disabled_uses_shared_bridge_error_envelope(monkeypatch) -> None:
    service = _Service(
        BridgeError(
            "local_script_database_disabled",
            "Local script database features are disabled by configuration.",
        )
    )
    _install(monkeypatch, service)

    result = runner.invoke(app, ["search", "script", "anything"])

    assert result.exit_code == 1
    assert result.stdout == (
        '{"error":true,"code":"local_script_database_disabled",'
        '"message":"Local script database features are disabled by configuration."}\n'
    )
