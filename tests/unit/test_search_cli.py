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


def test_root_help_exposes_search_and_phase22_exposes_live_code_subcommands() -> None:
    root = runner.invoke(app, ["--help"])
    search = runner.invoke(app, ["search", "--help"])

    assert root.exit_code == 0
    assert "search" in root.stdout
    assert search.exit_code == 0
    for command in ("script", "python", "vex"):
        assert command in search.stdout
    assert "node" not in search.stdout


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


class _LiveService:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def search(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def _install_live(monkeypatch, service: _LiveService) -> None:
    settings = SimpleNamespace()
    monkeypatch.setattr(search_cmd, "load_config", lambda: settings)
    monkeypatch.setattr(search_cmd, "_live_code_service", lambda _settings: service)
    monkeypatch.setattr(search_cmd.OutputPolicy, "from_config", lambda _settings: _Policy())


def test_python_and_vex_commands_share_identical_live_code_options(monkeypatch) -> None:
    hit = {
        "hits": [
            {
                "path": "/obj/geo1/python1",
                "node_type": "python",
                "resource": "resource-code-001",
                "score": CanonicalJsonNumber("317.540323"),
            }
        ]
    }
    service = _LiveService(hit)
    _install_live(monkeypatch, service)

    python = runner.invoke(
        app,
        [
            "search", "python", "geometry", "--top-k", "7",
            "--path", "/obj/geo*", "--recursive", "--session", "2",
        ],
    )
    vex = runner.invoke(
        app,
        ["search", "vex", "--like", "/obj/geo1/wrangle1", "--session", "3"],
    )

    assert python.exit_code == 0
    assert python.stdout == (
        '{"hits":[{"path":"/obj/geo1/python1","node_type":"python",'
        '"resource":"resource-code-001","score":317.540323}]}\n'
    )
    assert vex.exit_code == 0
    assert service.calls == [
        {
            "language": "python",
            "query": "geometry",
            "like": None,
            "top_k": 7,
            "path": "/obj/geo*",
            "recursive": True,
            "session": 2,
        },
        {
            "language": "vex",
            "query": None,
            "like": "/obj/geo1/wrangle1",
            "top_k": 10,
            "path": None,
            "recursive": False,
            "session": 3,
        },
    ]


def test_live_code_query_mode_errors_use_specified_code(monkeypatch) -> None:
    service = _LiveService(
        BridgeError(
            "invalid_code_search_query",
            "Exactly one of QUERY or --like NODE_PATH must be supplied.",
        )
    )
    _install_live(monkeypatch, service)

    result = runner.invoke(app, ["search", "python"])

    assert result.exit_code == 1
    assert '"code":"invalid_code_search_query"' in result.stdout


def test_live_code_help_exposes_only_current_options() -> None:
    python = runner.invoke(app, ["search", "python", "--help"])
    vex = runner.invoke(app, ["search", "vex", "--help"])

    assert python.exit_code == vex.exit_code == 0
    for output in (python.stdout, vex.stdout):
        for option in ("--top-k", "--like", "--path", "--recursive", "--session"):
            assert option in output
        for forbidden in ("--root", "--port", "--hcommand"):
            assert forbidden not in output
