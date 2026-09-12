from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from houbridge.config import HoudiniConfig
from houbridge.errors import BridgeError
from houbridge.houdini.transport import HoudiniTarget, HoudiniTransport


def _make_hcommand(root: Path) -> Path:
    bin_dir = root / "bin"
    bin_dir.mkdir(parents=True)
    executable = bin_dir / "hcommand.exe"
    executable.write_bytes(b"")
    return executable


def test_transport_invokes_hcommand_with_port_and_python_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    script = tmp_path / "run.py"
    script.write_text("pass", encoding="utf-8")
    captured: dict[str, object] = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    transport = HoudiniTransport("hcommand-test", timeout_seconds=7)

    result = transport.execute_script(HoudiniTarget("127.0.0.1", 1714), script)

    assert captured["args"] == [
        "hcommand-test",
        "1714",
        f'python "{script.resolve().as_posix()}"',
    ]
    assert captured["kwargs"]["timeout"] == 7  # type: ignore[index]
    assert result.stdout == "ok"


@pytest.mark.parametrize("host", ["localhost", "localhost.", "127.0.0.1", "::1"])
def test_transport_accepts_loopback_targets(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    host: str,
) -> None:
    script = tmp_path / "run.py"
    script.write_text("pass", encoding="utf-8")
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda args, **kwargs: subprocess.CompletedProcess(
            args=args, returncode=0, stdout="", stderr=""
        ),
    )

    HoudiniTransport("hcommand-test", timeout_seconds=1).execute_script(
        HoudiniTarget(host, 1714),
        script,
    )


def test_transport_rejects_non_loopback_before_subprocess(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    script = tmp_path / "run.py"
    script.write_text("pass", encoding="utf-8")

    def fail_if_called(*args, **kwargs):
        raise AssertionError("subprocess must not run for a remote target")

    monkeypatch.setattr(subprocess, "run", fail_if_called)

    with pytest.raises(BridgeError) as caught:
        HoudiniTransport("hcommand-test", timeout_seconds=1).execute_script(
            HoudiniTarget("192.0.2.10", 1714),
            script,
        )

    assert caught.value.code == "remote_target_disabled"


def test_transport_reports_timeout(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    script = tmp_path / "run.py"
    script.write_text("pass", encoding="utf-8")

    def timeout(args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args, timeout=kwargs["timeout"])

    monkeypatch.setattr(subprocess, "run", timeout)

    with pytest.raises(BridgeError) as caught:
        HoudiniTransport("hcommand-test", timeout_seconds=2.5).execute_script(
            HoudiniTarget("localhost", 1714),
            script,
        )

    assert caught.value.code == "hcommand_timeout"


def test_transport_reports_missing_hcommand(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    script = tmp_path / "run.py"
    script.write_text("pass", encoding="utf-8")

    def missing(*args, **kwargs):
        raise FileNotFoundError("missing")

    monkeypatch.setattr(subprocess, "run", missing)

    with pytest.raises(BridgeError) as caught:
        HoudiniTransport("missing-hcommand", timeout_seconds=1).execute_script(
            HoudiniTarget("localhost", 1714),
            script,
        )

    assert caught.value.code == "hcommand_not_found"


def test_transport_reports_nonzero_hcommand_exit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    script = tmp_path / "run.py"
    script.write_text("pass", encoding="utf-8")
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda args, **kwargs: subprocess.CompletedProcess(
            args=args,
            returncode=4,
            stdout="",
            stderr="socket failed",
        ),
    )

    with pytest.raises(BridgeError) as caught:
        HoudiniTransport("hcommand-test", timeout_seconds=1).execute_script(
            HoudiniTarget("localhost", 1714),
            script,
        )

    assert caught.value.code == "houdini_transport_failed"
    assert caught.value.detail == "socket failed"


def test_transport_from_config_does_not_treat_launch_hcommand_as_transport_tool(
    tmp_path: Path,
) -> None:
    root = tmp_path / "Houdini21.0.1"
    transport_executable = _make_hcommand(root)
    settings = HoudiniConfig(
        hcommand=str(tmp_path / "configured-launch-houdini.exe"),
        transport_timeout_seconds=9,
        lock_timeout_seconds=120,
        startup_timeout_seconds=60,
        startup_poll_interval_seconds=0.25,
    )

    transport = HoudiniTransport.from_config(
        settings,
        environ={"HFS": str(root), "PATH": ""},
        platform="win32",
    )

    assert transport.executable == transport_executable.resolve()
    assert transport.timeout_seconds == 9


def test_houdini_scripts_have_a_physical_package_boundary() -> None:
    import houbridge.houdini.scripts as scripts

    package_dir = Path(scripts.__file__).parent
    assert package_dir.name == "scripts"
    assert package_dir.parent.name == "houdini"


def test_transport_can_start_async_script_without_sync_timeout(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    script = tmp_path / "run.py"
    script.write_text("pass", encoding="utf-8")
    captured: dict[str, object] = {}

    class FakeProcess:
        def poll(self):
            return None

        def terminate(self):
            return None

    def fake_popen(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return FakeProcess()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    process = HoudiniTransport("hcommand-test", timeout_seconds=0.01).start_script(
        HoudiniTarget("localhost", 1714),
        script,
    )

    assert process.poll() is None
    assert captured["args"] == [
        "hcommand-test",
        "1714",
        f'python "{script.resolve().as_posix()}"',
    ]
    assert "timeout" not in captured["kwargs"]  # type: ignore[operator]
