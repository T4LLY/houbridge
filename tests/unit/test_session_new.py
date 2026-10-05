from __future__ import annotations

import json
import os
import shutil
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from houbridge.config import HoudiniConfig
from houbridge.errors import BridgeError
from houbridge.process_coordination import ProcessIdentity
from houbridge.session.launcher import HoudiniSessionLauncher, SessionLaunchResult
from houbridge.session.new import SessionNewService
from houbridge.session.probe import SessionProbeResult
from houbridge.session.registry import SessionRecord, SessionRegistry, SessionRegistryState
from houbridge.temporary_workspace import TemporaryWorkspaceService


class FakeProcess:
    def __init__(self, pid: int = 9000, returncode: int | None = None) -> None:
        self.pid = pid
        self.returncode = returncode
        self.terminated = False
        self.killed = False

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = -15

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9

    def wait(self, timeout: float | None = None) -> int:
        return self.returncode or 0


class FakeProbe:
    def __init__(self, result: SessionProbeResult) -> None:
        self.result = result
        self.calls: list[int] = []

    def inspect(self, port: int) -> SessionProbeResult:
        self.calls.append(port)
        return self.result


def _config(*, timeout: float = 1.0, poll: float = 0.01, hcommand: str = "") -> HoudiniConfig:
    return HoudiniConfig(
        hcommand=hcommand,
        transport_timeout_seconds=120.0,
        lock_timeout_seconds=120.0,
        startup_timeout_seconds=timeout,
        startup_poll_interval_seconds=poll,
    )


def _launch_result(*, pid: int = 18744, port: int = 49153) -> SessionLaunchResult:
    probe = SessionProbeResult(
        pid=pid,
        version="22.0.429",
        license="Commercial",
        file=None,
        headless=False,
        open_ports=(port,),
    )
    return SessionLaunchResult(
        pid=pid,
        port=port,
        identity=ProcessIdentity(pid, f"start-{pid}"),
        probe=probe,
        process=FakeProcess(pid),
    )


class FakeLauncher:
    def __init__(self, result: SessionLaunchResult) -> None:
        self.result = result
        self.calls: list[dict[str, object]] = []
        self.released: list[SessionLaunchResult] = []
        self.terminated: list[SessionLaunchResult] = []

    def launch(self, **kwargs) -> SessionLaunchResult:
        self.calls.append(kwargs)
        return self.result

    def release(self, result: SessionLaunchResult) -> None:
        self.released.append(result)

    def terminate(self, result: SessionLaunchResult) -> None:
        self.terminated.append(result)


def test_first_session_becomes_session_one_and_primary(tmp_path: Path) -> None:
    registry = SessionRegistry(tmp_path / "sessions.json")
    launcher = FakeLauncher(_launch_result())
    service = SessionNewService(registry, launcher)  # type: ignore[arg-type]

    payload = service.create()

    assert payload == {"session": 1, "port": 49153, "pid": 18744}
    state = registry.load()
    assert state.primary == 1
    assert state.sessions[1].process_start_identity == "start-18744"
    assert len(launcher.calls) == 1
    assert launcher.released == [launcher.result]


def test_concurrent_new_calls_allocate_distinct_sessions(tmp_path: Path) -> None:
    path = tmp_path / "sessions.json"
    start = threading.Barrier(2)
    results: list[dict[str, object]] = []
    errors: list[BaseException] = []
    result_lock = threading.Lock()

    class SlowRegistry(SessionRegistry):
        def load(self) -> SessionRegistryState:
            state = super().load()
            time.sleep(0.05)
            return state

    class SynchronizedLauncher(FakeLauncher):
        def launch(self, **kwargs) -> SessionLaunchResult:
            start.wait(timeout=2)
            return super().launch(**kwargs)

    def run(pid: int, port: int) -> None:
        registry = SlowRegistry(path)
        launcher = SynchronizedLauncher(_launch_result(pid=pid, port=port))
        service = SessionNewService(
            registry,
            launcher,  # type: ignore[arg-type]
            identity_reader=lambda value: ProcessIdentity(value, f"start-{value}"),
        )
        try:
            payload = service.create()
        except BaseException as exc:
            with result_lock:
                errors.append(exc)
        else:
            with result_lock:
                results.append(payload)

    first = threading.Thread(target=run, args=(2001, 49153))
    second = threading.Thread(target=run, args=(2002, 49154))
    first.start()
    second.start()
    first.join(timeout=5)
    second.join(timeout=5)

    assert not first.is_alive()
    assert not second.is_alive()
    assert errors == []
    assert {payload["session"] for payload in results} == {1, 2}

    state = SessionRegistry(path).load()
    assert state.primary == 1
    assert set(state.sessions) == {1, 2}
    assert {record.pid for record in state.sessions.values()} == {2001, 2002}

def test_additional_session_never_reuses_a_live_process(tmp_path: Path) -> None:
    registry = SessionRegistry(tmp_path / "sessions.json")
    registry.save(
        SessionRegistryState(
            primary=1,
            sessions={
                1: SessionRecord(
                    session=1,
                    port=49152,
                    pid=1001,
                    process_start_identity="live-1",
                )
            },
        )
    )
    launcher = FakeLauncher(_launch_result(pid=2002, port=49154))
    service = SessionNewService(
        registry,
        launcher,  # type: ignore[arg-type]
        identity_reader=lambda pid: ProcessIdentity(pid, "live-1"),
    )

    payload = service.create()

    assert payload["session"] == 2
    assert registry.load().primary == 1
    assert len(launcher.calls) == 1


def test_stale_session_number_is_reused_and_stale_primary_is_not_replaced(tmp_path: Path) -> None:
    registry = SessionRegistry(tmp_path / "sessions.json")
    registry.save(
        SessionRegistryState(
            primary=2,
            sessions={
                1: SessionRecord(session=1, port=49151, pid=1001),
                2: SessionRecord(session=2, port=49152, pid=1002),
                3: SessionRecord(session=3, port=49153, pid=1003),
            },
        )
    )
    launcher = FakeLauncher(_launch_result(pid=2002, port=49154))

    def identity(pid: int) -> ProcessIdentity:
        if pid == 1002:
            raise ProcessLookupError(pid)
        return ProcessIdentity(pid, f"live-{pid}")

    payload = SessionNewService(
        registry,
        launcher,  # type: ignore[arg-type]
        identity_reader=identity,
    ).create()

    assert payload["session"] == 2
    state = registry.load()
    assert state.primary is None
    assert set(state.sessions) == {1, 2, 3}
    assert state.sessions[2].pid == 2002


def test_stale_cleanup_that_removes_all_live_sessions_promotes_new_session(tmp_path: Path) -> None:
    registry = SessionRegistry(tmp_path / "sessions.json")
    registry.save(
        SessionRegistryState(
            primary=1,
            sessions={1: SessionRecord(session=1, port=49152, pid=1001)},
        )
    )
    launcher = FakeLauncher(_launch_result(pid=2002, port=49153))

    def identity(pid: int) -> ProcessIdentity:
        raise ProcessLookupError(pid)

    SessionNewService(
        registry,
        launcher,  # type: ignore[arg-type]
        identity_reader=identity,
    ).create()

    state = registry.load()
    assert state.primary == 1
    assert set(state.sessions) == {1}
    assert state.sessions[1].pid == 2002


def test_existing_registry_without_primary_and_without_live_sessions_promotes_new_session(tmp_path: Path) -> None:
    registry = SessionRegistry(tmp_path / "sessions.json")
    registry.save(SessionRegistryState(primary=None, sessions={}))
    launcher = FakeLauncher(_launch_result())

    SessionNewService(registry, launcher).create()  # type: ignore[arg-type]

    assert registry.load().primary == 1


def test_existing_registry_without_primary_but_with_live_sessions_does_not_promote_new_session(tmp_path: Path) -> None:
    registry = SessionRegistry(tmp_path / "sessions.json")
    registry.save(
        SessionRegistryState(
            primary=None,
            sessions={
                1: SessionRecord(
                    session=1,
                    port=49152,
                    pid=1001,
                    process_start_identity="live-1",
                )
            },
        )
    )
    launcher = FakeLauncher(_launch_result(pid=2002, port=49153))

    SessionNewService(
        registry,
        launcher,  # type: ignore[arg-type]
        identity_reader=lambda pid: ProcessIdentity(pid, "live-1") if pid == 1001 else ProcessIdentity(pid, f"start-{pid}"),
    ).create()

    assert registry.load().primary is None


def test_launcher_release_reaps_successful_process_in_background(tmp_path: Path) -> None:
    executable = tmp_path / "houdini"
    executable.write_bytes(b"")
    waited = threading.Event()

    class WaitProcess(FakeProcess):
        def wait(self, timeout: float | None = None) -> int:
            waited.set()
            return 0

    process = WaitProcess(pid=18744)
    launcher = HoudiniSessionLauncher(
        _config(),
        lambda _executable: FakeProbe(
            SessionProbeResult(
                pid=18744,
                version="22.0.429",
                license="Commercial",
                file=None,
                headless=False,
                open_ports=(49153,),
            )
        ),
        popen=lambda *args, **kwargs: process,
        executable_resolver=lambda *args, **kwargs: executable,
    )
    result = _launch_result(pid=18744, port=49153)
    result = SessionLaunchResult(
        pid=result.pid,
        port=result.port,
        identity=result.identity,
        probe=result.probe,
        process=process,
    )

    launcher.release(result)

    assert waited.wait(timeout=1.0)


def test_launcher_uses_hbatch_native_openport_wait_for_headless_runtime(tmp_path: Path) -> None:
    executable = tmp_path / "hbatch.exe"
    executable.write_bytes(b"")
    process = FakeProcess(pid=18744)
    captured: dict[str, object] = {}
    requested = tmp_path / "scene.hip"
    requested.write_bytes(b"hip")

    class Probe:
        def inspect(self, port: int) -> SessionProbeResult:
            return SessionProbeResult(
                pid=18744,
                version="22.0.429",
                license="Commercial",
                file=str(requested.resolve()),
                headless=True,
                open_ports=(port,),
            )

    class HeadlessInput:
        def __init__(self) -> None:
            self.writes: list[str] = []
            self.closed = False

        def write(self, value: str) -> int:
            self.writes.append(value)
            return len(value)

        def flush(self) -> None:
            env = captured["kwargs"]["env"]
            bootstrap_dir = Path(env["HOUBRIDGE_SESSION_BOOTSTRAP_DIR"])
            text = "".join(self.writes)
            if "openport -a -q -r" in text:
                (bootstrap_dir / "bootstrap.result.json").write_text(
                    json.dumps({"pid": 18744, "port": 49153}),
                    encoding="utf-8",
                )
            if "openport -q -w 49153" in text:
                (bootstrap_dir / "bootstrap.rebind.ready").write_text(
                    "ready\n", encoding="utf-8"
                )

        def close(self) -> None:
            self.closed = True

    input_stream = HeadlessInput()
    process.stdin = input_stream  # type: ignore[attr-defined]

    def popen(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return process

    launcher = HoudiniSessionLauncher(
        _config(),
        lambda executable: Probe(),  # type: ignore[arg-type]
        workspaces=TemporaryWorkspaceService(temp_root=tmp_path / "temp"),
        popen=popen,
        identity_reader=lambda pid: ProcessIdentity(pid, "start"),
        executable_resolver=lambda *args, **kwargs: executable,
        port_ready=lambda port: port == 49153,
        python_executable=tmp_path / "python.exe",
        platform="win32",
        environ={"PATH": ""},
    )

    result = launcher.launch(hip_file=requested, headless=True)

    assert result.port == 49153
    assert captured["args"] == [str(executable), str(requested.resolve())]
    commands = "".join(input_stream.writes)
    assert "openport -a -q -r" in commands
    assert "openport -q -w 49153" in commands
    assert "quit -f" in commands
    assert "-b" not in captured["args"]
    assert "-i" not in captured["args"]
    assert input_stream.closed is True
    launch_env = captured["kwargs"]["env"]
    assert Path(launch_env["HOUBRIDGE_SESSION_BOOTSTRAP_DIR"]).name.startswith("session-new-")


def test_launcher_timeout_terminates_launched_process(tmp_path: Path) -> None:
    executable = tmp_path / "houdini.exe"
    executable.write_bytes(b"")
    process = FakeProcess(pid=18744)

    class Clock:
        value = 0.0

        def monotonic(self) -> float:
            return self.value

        def sleep(self, value: float) -> None:
            self.value += value

    clock = Clock()
    launcher = HoudiniSessionLauncher(
        _config(timeout=0.2, poll=0.1),
        lambda executable: FakeProbe(  # unused
            SessionProbeResult(18744, "22.0.429", "Commercial", None, False, (49153,))
        ),  # type: ignore[arg-type]
        workspaces=TemporaryWorkspaceService(temp_root=tmp_path / "temp"),
        popen=lambda *args, **kwargs: process,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
        executable_resolver=lambda *args, **kwargs: executable,
        platform="win32",
        environ={"PATH": ""},
    )

    with pytest.raises(BridgeError) as caught:
        launcher.launch()

    assert caught.value.code == "houdini_startup_timeout"
    assert process.terminated is True


def test_unreadable_or_missing_hip_is_rejected_before_launch(tmp_path: Path) -> None:
    executable = tmp_path / "houdini.exe"
    executable.write_bytes(b"")
    called = False

    def popen(*args, **kwargs):
        nonlocal called
        called = True
        return FakeProcess()

    launcher = HoudiniSessionLauncher(
        _config(),
        lambda executable: FakeProbe(SessionProbeResult(1, "x", "x", None, False, (1,))),  # type: ignore[arg-type]
        workspaces=TemporaryWorkspaceService(temp_root=tmp_path / "temp"),
        popen=popen,
        executable_resolver=lambda *args, **kwargs: executable,
        platform="win32",
        environ={"PATH": ""},
    )

    with pytest.raises(BridgeError) as caught:
        launcher.launch(hip_file=tmp_path / "missing.hip")

    assert caught.value.code == "session_file_unreadable"
    assert called is False


def test_windows_launch_uses_new_process_group_for_ctrl_c_isolation(tmp_path: Path, monkeypatch) -> None:
    executable = tmp_path / "houdini.exe"
    executable.write_bytes(b"")
    process = FakeProcess(pid=18744)
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        "houbridge.session.launcher.subprocess.CREATE_NEW_PROCESS_GROUP",
        0x00000200,
        raising=False,
    )

    class Probe:
        def inspect(self, port: int) -> SessionProbeResult:
            return SessionProbeResult(
                pid=18744,
                version="22.0.429",
                license="Commercial",
                file=None,
                headless=False,
                open_ports=(port,),
            )

    def popen(args, **kwargs):
        captured.update(kwargs)
        script = Path(args[-1])
        script.with_name("bootstrap.result.json").write_text(
            json.dumps({"pid": 18744, "port": 49153}), encoding="utf-8"
        )
        return process

    launcher = HoudiniSessionLauncher(
        _config(),
        lambda executable: Probe(),  # type: ignore[arg-type]
        workspaces=TemporaryWorkspaceService(temp_root=tmp_path / "temp"),
        popen=popen,
        identity_reader=lambda pid: ProcessIdentity(pid, "start"),
        executable_resolver=lambda *args, **kwargs: executable,
        platform="win32",
        environ={"PATH": ""},
    )

    launcher.launch()

    assert captured["creationflags"] & 0x00000200


def test_physical_bootstrap_loads_file_and_uses_automatic_openport(tmp_path: Path, monkeypatch) -> None:
    source = (
        Path(__file__).parents[2]
        / "src"
        / "houbridge"
        / "houdini"
        / "scripts"
        / "session"
        / "bootstrap.py"
    )
    script = tmp_path / "bootstrap.py"
    shutil.copyfile(source, script)
    requested = tmp_path / "scene.hip"
    requested.write_bytes(b"hip")
    script.with_name("bootstrap.request.json").write_text(
        json.dumps({"file": str(requested), "headless": False}), encoding="utf-8"
    )
    calls: list[str] = []
    loaded: list[str] = []
    fake_hou = SimpleNamespace(
        hscript=lambda command: (calls.append(command) or ("49153\n", "")),
        hipFile=SimpleNamespace(load=lambda path: loaded.append(path)),
    )
    monkeypatch.setitem(sys.modules, "hou", fake_hou)
    monkeypatch.setattr(os, "getpid", lambda: 18744)
    monkeypatch.setenv("HOUBRIDGE_SESSION_BOOTSTRAP_DIR", str(tmp_path))

    namespace = {"__name__": "__main__"}
    exec(compile(script.read_text(encoding="utf-8"), str(script), "exec"), namespace)

    assert "__file__" not in namespace
    payload = json.loads(script.with_name("bootstrap.result.json").read_text(encoding="utf-8"))
    assert payload == {"pid": 18744, "port": 49153}
    assert calls == ["openport -a -q"]
    assert loaded == [str(requested)]


def test_physical_headless_port_notifier_publishes_selected_port(
    tmp_path: Path, monkeypatch
) -> None:
    source = (
        Path(__file__).parents[2]
        / "src"
        / "houbridge"
        / "houdini"
        / "scripts"
        / "session"
        / "headless_port_notifier.py"
    )
    script = tmp_path / "headless_port_notifier.py"
    shutil.copyfile(source, script)
    monkeypatch.setenv("HOUBRIDGE_SESSION_BOOTSTRAP_DIR", str(tmp_path))
    monkeypatch.setattr(sys, "argv", [str(script), "18744", "49153"])

    with pytest.raises(SystemExit) as caught:
        exec(compile(script.read_text(encoding="utf-8"), str(script), "exec"), {"__name__": "__main__"})

    assert caught.value.code == 0
    assert json.loads((tmp_path / "bootstrap.result.json").read_text(encoding="utf-8")) == {
        "pid": 18744,
        "port": 49153,
    }


def test_physical_headless_rebind_publishes_ready_marker(
    tmp_path: Path, monkeypatch
) -> None:
    source = (
        Path(__file__).parents[2]
        / "src"
        / "houbridge"
        / "houdini"
        / "scripts"
        / "session"
        / "headless_rebind.py"
    )
    script = tmp_path / "headless_rebind.py"
    shutil.copyfile(source, script)
    monkeypatch.setenv("HOUBRIDGE_SESSION_BOOTSTRAP_DIR", str(tmp_path))

    exec(compile(script.read_text(encoding="utf-8"), str(script), "exec"), {"__name__": "__main__"})

    assert (tmp_path / "bootstrap.rebind.ready").read_text(encoding="utf-8") == "ready\n"


def test_session_new_forwards_stale_records_to_cleanup_hook(tmp_path: Path) -> None:
    registry = SessionRegistry(tmp_path / "sessions.json")
    stale = SessionRecord(1, 49151, 1001, "old-start")
    registry.save(SessionRegistryState(primary=1, sessions={1: stale}))
    launcher = FakeLauncher(_launch_result(pid=2002, port=49154))
    retired: list[SessionRecord] = []

    def identity(pid: int) -> ProcessIdentity:
        raise ProcessLookupError(pid)

    SessionNewService(
        registry,
        launcher,  # type: ignore[arg-type]
        identity_reader=identity,
        on_stale=retired.append,
    ).create()

    assert retired == [stale]


def test_session_new_survives_stale_retirement_failure(tmp_path: Path) -> None:
    registry = SessionRegistry(tmp_path / "sessions.json")
    stale = SessionRecord(1, 49151, 1001, "old-start")
    registry.save(SessionRegistryState(primary=1, sessions={1: stale}))
    launcher = FakeLauncher(_launch_result(pid=2002, port=49154))

    def identity(pid: int) -> ProcessIdentity:
        raise ProcessLookupError(pid)

    def failing_retirement(_record: SessionRecord) -> None:
        raise PermissionError("simulated locked History directory")

    payload = SessionNewService(
        registry,
        launcher,  # type: ignore[arg-type]
        identity_reader=identity,
        on_stale=failing_retirement,
    ).create()

    assert payload == {"session": 1, "port": 49154, "pid": 2002}
    state = registry.load()
    assert state.primary == 1
    assert state.sessions[1].pid == 2002
    assert launcher.terminated == []


def test_launcher_failure_preserves_session_diagnostics(tmp_path: Path) -> None:
    executable = tmp_path / "houdini.exe"
    executable.write_bytes(b"")
    workspaces = TemporaryWorkspaceService(temp_root=tmp_path / "temp")
    process = FakeProcess(pid=18744, returncode=1)
    launcher = HoudiniSessionLauncher(
        _config(),
        lambda executable: FakeProbe(  # unused
            SessionProbeResult(18744, "22.0.429", "Commercial", None, False, (49153,))
        ),  # type: ignore[arg-type]
        workspaces=workspaces,
        popen=lambda *args, **kwargs: process,
        executable_resolver=lambda *args, **kwargs: executable,
        platform="win32",
        environ={"PATH": ""},
    )

    with pytest.raises(BridgeError) as caught:
        launcher.launch()

    assert caught.value.code == "houdini_launch_failed"
    diagnostics = next(workspaces.root.iterdir())
    assert f"launch_diagnostics={diagnostics}" in (caught.value.detail or "")
    assert (diagnostics / "bootstrap.py").is_file()
    assert json.loads((diagnostics / "bootstrap.request.json").read_text(encoding="utf-8")) == {
        "file": None,
        "headless": False,
    }
    context = json.loads((diagnostics / "launch.context.json").read_text(encoding="utf-8"))
    assert context["executable"] == str(executable)
    assert context["headless"] is False
    assert "houdini_launch_failed" in (diagnostics / "launch.error.txt").read_text(
        encoding="utf-8"
    )


def test_launcher_success_removes_session_diagnostics_workspace(tmp_path: Path) -> None:
    executable = tmp_path / "houdini.exe"
    executable.write_bytes(b"")
    workspaces = TemporaryWorkspaceService(temp_root=tmp_path / "temp")
    process = FakeProcess(pid=18744)

    class Probe:
        def inspect(self, port: int) -> SessionProbeResult:
            return SessionProbeResult(
                pid=18744,
                version="22.0.429",
                license="Commercial",
                file=None,
                headless=False,
                open_ports=(port,),
            )

    def popen(args, **kwargs):
        script = Path(args[-1])
        script.with_name("bootstrap.result.json").write_text(
            json.dumps({"pid": 18744, "port": 49153}),
            encoding="utf-8",
        )
        return process

    launcher = HoudiniSessionLauncher(
        _config(),
        lambda executable: Probe(),  # type: ignore[arg-type]
        workspaces=workspaces,
        popen=popen,
        identity_reader=lambda pid: ProcessIdentity(pid, "start"),
        executable_resolver=lambda *args, **kwargs: executable,
        platform="win32",
        environ={"PATH": ""},
    )

    launcher.launch()

    assert list(workspaces.root.iterdir()) == []
