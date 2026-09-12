from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from typer.testing import CliRunner

from houbridge.cli.main import app
from houbridge.execution.presentation import SynchronousExecutionResult
from houbridge.output.policy import OutputPolicy
from houbridge.output.tokens import FallbackTokenEstimator


class _Store:
    def __init__(self) -> None:
        self.payloads: list[bytes] = []

    def put_bytes(self, payload: bytes):
        self.payloads.append(payload)
        return SimpleNamespace(semantic_alias="whole-exec-result-000")


class _Service:
    def __init__(self, result: SynchronousExecutionResult) -> None:
        self.result = result
        self.calls = []

    def execute(self, invocation, *, session=None):
        self.calls.append((invocation, session))
        return self.result


def _install_fake_command_runtime(monkeypatch, result: SynchronousExecutionResult):
    from houbridge.cli import exec_cmd

    store = _Store()
    policy = OutputPolicy(
        inline_max_tokens=4096,
        token_estimator=FallbackTokenEstimator(),
        resource_store_factory=lambda: store,  # type: ignore[arg-type]
    )
    service = _Service(result)
    settings = object()
    monkeypatch.setattr(exec_cmd, "load_config", lambda: settings)
    monkeypatch.setattr(exec_cmd.OutputPolicy, "from_config", lambda _settings: policy)
    monkeypatch.setattr(
        exec_cmd,
        "_build_sync_execution_service",
        lambda _settings, received_policy: service
        if received_policy is policy
        else (_ for _ in ()).throw(AssertionError("wrong policy")),
    )
    return service, store


def test_root_help_exposes_exec_and_exec_help_has_current_options() -> None:
    runner = CliRunner()

    root = runner.invoke(app, ["--help"])
    command = runner.invoke(app, ["exec", "--help"])

    assert root.exit_code == 0
    assert "exec" in root.stdout
    assert command.exit_code == 0
    assert "--file" in command.stdout
    assert "--purpose" in command.stdout
    assert "--session" in command.stdout
    assert "--code" not in command.stdout
    assert "--inline-max-tokens" not in command.stdout
    assert "--port" not in command.stdout
    assert "--root" not in command.stdout
    assert "--hcommand" not in command.stdout
    assert "--async" in command.stdout


def test_exec_preserves_script_args_order_duplicates_and_purpose(
    monkeypatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "tool.py"
    source.write_text("result = 1\n", encoding="utf-8")
    service, _store = _install_fake_command_runtime(
        monkeypatch,
        SynchronousExecutionResult({"result": 1}, 0),
    )

    result = CliRunner().invoke(
        app,
        [
            "exec",
            "--file",
            str(source),
            "--purpose",
            "build preview geometry",
            "--session",
            "3",
            "--",
            "--quality",
            "high",
            "--quality",
            "low",
        ],
    )

    assert result.exit_code == 0
    assert result.stdout == '{"result":1}\n'
    invocation, selection = service.calls[0]
    assert selection == 3
    assert invocation.source_path == str(source)
    assert invocation.argv == (
        str(source),
        "--quality",
        "high",
        "--quality",
        "low",
    )
    assert invocation.purpose == "build preview geometry"


def test_exec_python_failure_emits_failure_envelope_and_exits_one(
    monkeypatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "tool.py"
    source.write_text("raise RuntimeError('boom')\n", encoding="utf-8")
    _service, _store = _install_fake_command_runtime(
        monkeypatch,
        SynchronousExecutionResult(
            {
                "error": True,
                "code": "execution_failed",
                "message": "Python execution failed inside Houdini.",
                "resource": "error-traceback-000",
            },
            1,
        ),
    )

    result = CliRunner().invoke(app, ["exec", "--file", str(source)])

    assert result.exit_code == 1
    assert json.loads(result.stdout) == {
        "error": True,
        "code": "execution_failed",
        "message": "Python execution failed inside Houdini.",
        "resource": "error-traceback-000",
    }


def test_exec_file_read_failure_uses_bridge_error_envelope(tmp_path: Path) -> None:
    missing = tmp_path / "missing.py"

    result = CliRunner().invoke(app, ["exec", "--file", str(missing)])

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["error"] is True
    assert payload["code"] == "python_file_read_failed"
    assert "Unable to read Python file" in payload["message"]


def test_exec_rejects_nul_before_building_dispatch_runtime(monkeypatch, tmp_path: Path) -> None:
    from houbridge.cli import exec_cmd

    source = tmp_path / "nul.py"
    source.write_bytes(b"print('before')\x00\n")
    built = False

    def should_not_build(*_args, **_kwargs):
        nonlocal built
        built = True
        raise AssertionError("dispatch runtime must not be built")

    monkeypatch.setattr(exec_cmd, "_build_sync_execution_service", should_not_build)

    result = CliRunner().invoke(app, ["exec", "--file", str(source)])

    assert result.exit_code == 1
    assert json.loads(result.stdout)["code"] == "invalid_python_source"
    assert built is False


def test_exec_rejects_removed_code_option_as_framework_usage_error() -> None:
    result = CliRunner().invoke(app, ["exec", "--code", "result = 1"])

    assert result.exit_code == 2
    assert "--code" in result.stderr


def test_exec_async_returns_only_task_reference(monkeypatch, tmp_path: Path) -> None:
    from houbridge.cli import exec_cmd

    source = tmp_path / "tool.py"
    source.write_text("print('hello')\n", encoding="utf-8")

    class Submitter:
        def __init__(self) -> None:
            self.calls = []

        def submit(self, invocation, *, session=None):
            self.calls.append((invocation, session))
            return "geometry-build-cache-000"

    submitter = Submitter()
    store = _Store()
    policy = OutputPolicy(
        inline_max_tokens=4096,
        token_estimator=FallbackTokenEstimator(),
        resource_store_factory=lambda: store,  # type: ignore[arg-type]
    )
    monkeypatch.setattr(exec_cmd, "load_config", lambda: object())
    monkeypatch.setattr(exec_cmd.OutputPolicy, "from_config", lambda _settings: policy)
    monkeypatch.setattr(exec_cmd, "_build_async_execution_submitter", lambda _settings: submitter)

    result = CliRunner().invoke(
        app,
        ["exec", "--file", str(source), "--async", "--session", "2", "--", "--quality", "high"],
    )

    assert result.exit_code == 0
    assert result.stdout == '{"task":"geometry-build-cache-000"}\n'
    invocation, session = submitter.calls[0]
    assert session == 2
    assert invocation.argv == (str(source), "--quality", "high")
