from __future__ import annotations

from typer.testing import CliRunner

from houbridge.cli.main import app


def test_root_help_exposes_implemented_session_family() -> None:
    result = CliRunner().invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "session" in result.stdout


def test_session_help_exposes_info_new_attach_detach_stop_and_promote() -> None:
    result = CliRunner().invoke(app, ["session", "--help"])

    assert result.exit_code == 0
    assert "info" in result.stdout
    assert "new" in result.stdout
    assert "attach" in result.stdout
    assert "detach" in result.stdout
    assert "stop" in result.stdout
    assert "promote" in result.stdout


def test_session_new_help_exposes_only_current_options() -> None:
    result = CliRunner().invoke(app, ["session", "new", "--help"])

    assert result.exit_code == 0
    assert "--file" in result.stdout
    assert "--headless" in result.stdout
    assert "--hcommand" in result.stdout
    assert "--port" not in result.stdout


def test_session_attach_help_explains_manual_openport() -> None:
    result = CliRunner().invoke(app, ["session", "attach", "--help"])

    assert result.exit_code == 0
    assert "PORT" in result.stdout
    assert "openport -a -q" in result.stdout


def test_session_attach_emits_exact_public_success_shape(monkeypatch, tmp_path) -> None:
    from types import SimpleNamespace

    from houbridge.cli import common, session_cmd

    monkeypatch.setattr(
        session_cmd,
        "load_config",
        lambda: SimpleNamespace(
            storage=SimpleNamespace(data_dir=tmp_path),
            houdini=SimpleNamespace(
                transport_timeout_seconds=120.0,
                lock_timeout_seconds=120.0,
            ),
        ),
    )
    monkeypatch.setattr(
        common,
        "load_config",
        lambda: SimpleNamespace(output=SimpleNamespace(inline_max_tokens=4096)),
    )
    monkeypatch.setattr(
        session_cmd.SessionAttachService,
        "attach",
        lambda self, port: {"session": 2, "port": port, "pid": 18744},
    )

    result = CliRunner().invoke(app, ["session", "attach", "49153"])

    assert result.exit_code == 0
    assert result.stdout == '{"session":2,"port":49153,"pid":18744}\n'


def test_session_new_emits_exact_public_success_shape(monkeypatch, tmp_path) -> None:
    from types import SimpleNamespace

    from houbridge.cli import common, session_cmd

    monkeypatch.setattr(
        session_cmd,
        "load_config",
        lambda: SimpleNamespace(
            storage=SimpleNamespace(data_dir=tmp_path),
            houdini=SimpleNamespace(
                transport_timeout_seconds=120.0,
                lock_timeout_seconds=120.0,
            ),
        ),
    )
    monkeypatch.setattr(
        common,
        "load_config",
        lambda: SimpleNamespace(output=SimpleNamespace(inline_max_tokens=4096)),
    )
    monkeypatch.setattr(
        session_cmd.SessionNewService,
        "create",
        lambda self, **kwargs: {"session": 2, "port": 49153, "pid": 18744},
    )

    result = CliRunner().invoke(app, ["session", "new", "--headless"])

    assert result.exit_code == 0
    assert result.stdout == '{"session":2,"port":49153,"pid":18744}\n'


def test_session_detach_emits_exact_public_success_shape(monkeypatch, tmp_path) -> None:
    from types import SimpleNamespace

    from houbridge.cli import common, session_cmd

    monkeypatch.setattr(
        session_cmd,
        "load_config",
        lambda: SimpleNamespace(
            storage=SimpleNamespace(data_dir=tmp_path),
            houdini=SimpleNamespace(lock_timeout_seconds=120.0),
        ),
    )
    monkeypatch.setattr(
        common,
        "load_config",
        lambda: SimpleNamespace(output=SimpleNamespace(inline_max_tokens=4096)),
    )
    monkeypatch.setattr(
        session_cmd.SessionDetachService,
        "detach",
        lambda self, session: {"detached": session},
    )

    result = CliRunner().invoke(app, ["session", "detach", "3"])

    assert result.exit_code == 0
    assert result.stdout == '{"detached":3}\n'


def test_session_stop_help_exposes_discard() -> None:
    result = CliRunner().invoke(app, ["session", "stop", "--help"])

    assert result.exit_code == 0
    assert "--discard" in result.stdout


def test_session_stop_emits_exact_public_success_shape(monkeypatch, tmp_path) -> None:
    from types import SimpleNamespace

    from houbridge.cli import common, session_cmd

    monkeypatch.setattr(
        session_cmd,
        "load_config",
        lambda: SimpleNamespace(
            storage=SimpleNamespace(data_dir=tmp_path),
            houdini=SimpleNamespace(
                transport_timeout_seconds=120.0,
                lock_timeout_seconds=120.0,
                startup_poll_interval_seconds=0.25,
            ),
        ),
    )
    monkeypatch.setattr(
        common,
        "load_config",
        lambda: SimpleNamespace(output=SimpleNamespace(inline_max_tokens=4096)),
    )
    monkeypatch.setattr(
        session_cmd.HoudiniTransport,
        "from_config",
        lambda *_args, **_kwargs: SimpleNamespace(),
    )
    calls: list[tuple[int, bool]] = []

    def stop(_self, session: int, *, discard: bool = False):
        calls.append((session, discard))
        return {"stopped": session}

    monkeypatch.setattr(session_cmd.SessionStopService, "stop", stop)

    result = CliRunner().invoke(app, ["session", "stop", "3"])

    assert result.exit_code == 0
    assert result.stdout == '{"stopped":3}\n'
    assert calls == [(3, False)]


def test_session_stop_discard_forwards_explicit_policy(monkeypatch, tmp_path) -> None:
    from types import SimpleNamespace

    from houbridge.cli import common, session_cmd

    monkeypatch.setattr(
        session_cmd,
        "load_config",
        lambda: SimpleNamespace(
            storage=SimpleNamespace(data_dir=tmp_path),
            houdini=SimpleNamespace(
                transport_timeout_seconds=120.0,
                lock_timeout_seconds=120.0,
                startup_poll_interval_seconds=0.25,
            ),
        ),
    )
    monkeypatch.setattr(
        common,
        "load_config",
        lambda: SimpleNamespace(output=SimpleNamespace(inline_max_tokens=4096)),
    )
    monkeypatch.setattr(
        session_cmd.HoudiniTransport,
        "from_config",
        lambda *_args, **_kwargs: SimpleNamespace(),
    )
    calls: list[tuple[int, bool]] = []

    def stop(_self, session: int, *, discard: bool = False):
        calls.append((session, discard))
        return {"stopped": session}

    monkeypatch.setattr(session_cmd.SessionStopService, "stop", stop)

    result = CliRunner().invoke(app, ["session", "stop", "3", "--discard"])

    assert result.exit_code == 0
    assert result.stdout == '{"stopped":3}\n'
    assert calls == [(3, True)]


def test_session_promote_emits_exact_public_success_shape(monkeypatch, tmp_path) -> None:
    from types import SimpleNamespace

    from houbridge.cli import common, session_cmd

    monkeypatch.setattr(
        session_cmd,
        "load_config",
        lambda: SimpleNamespace(
            storage=SimpleNamespace(data_dir=tmp_path),
            houdini=SimpleNamespace(
                transport_timeout_seconds=120.0,
                lock_timeout_seconds=120.0,
            ),
        ),
    )
    monkeypatch.setattr(
        common,
        "load_config",
        lambda: SimpleNamespace(output=SimpleNamespace(inline_max_tokens=4096)),
    )
    monkeypatch.setattr(
        session_cmd.SessionPromoteService,
        "promote",
        lambda self, session: {"primary": session},
    )

    result = CliRunner().invoke(app, ["session", "promote", "3"])

    assert result.exit_code == 0
    assert result.stdout == '{"primary":3}\n'
