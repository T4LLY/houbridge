from __future__ import annotations

import json
import os
import runpy
import shutil
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from houbridge.errors import BridgeError
from houbridge.houdini.transport import HoudiniTarget, TransportResult
from houbridge.process_coordination import ProcessIdentity, process_identity_for_pid
from houbridge.session.info import SessionInfoService
from houbridge.session.probe import SessionProbe, SessionProbeResult
from houbridge.session.registry import SessionRecord, SessionRegistry, SessionRegistryState
from houbridge.session.resolver import SessionResolver
from houbridge.session.stale import SessionStaleCleanupService
from houbridge.temporary_workspace import TemporaryWorkspaceService


class FakeProbe:
    def __init__(self, results: dict[int, SessionProbeResult]) -> None:
        self.results = results
        self.calls: list[int] = []

    def inspect(self, port: int) -> SessionProbeResult:
        self.calls.append(port)
        return self.results[port]


def _probe_result(
    *,
    pid: int,
    port: int,
    version: str = "22.0.429",
    license_name: str = "Commercial",
    file: str | None = "C:/project/test.hip",
    headless: bool = False,
) -> SessionProbeResult:
    return SessionProbeResult(
        pid=pid,
        version=version,
        license=license_name,
        file=file,
        headless=headless,
        open_ports=(port,),
    )


def _identity_reader(mapping: dict[int, str]):
    def read(pid: int) -> ProcessIdentity:
        return ProcessIdentity(pid=pid, process_start_identity=mapping[pid])

    return read


def test_missing_registry_is_empty(tmp_path: Path) -> None:
    state = SessionRegistry(tmp_path / "sessions.json").load()

    assert state.primary is None
    assert dict(state.sessions) == {}


def test_registry_round_trips_global_contract_and_internal_identity(tmp_path: Path) -> None:
    path = tmp_path / "global-data" / "sessions.json"
    registry = SessionRegistry(path)
    registry.save(
        SessionRegistryState(
            primary=3,
            sessions={
                1: SessionRecord(session=1, port=49152, pid=12340),
                3: SessionRecord(
                    session=3,
                    port=49154,
                    pid=18744,
                    process_start_identity="windows:123456",
                ),
            },
        )
    )

    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw == {
        "primary": 3,
        "sessions": {
            "1": {"port": 49152, "pid": 12340},
            "3": {
                "port": 49154,
                "pid": 18744,
                "process_start_identity": "windows:123456",
            },
        },
    }
    loaded = registry.load()
    assert loaded.primary == 3
    assert loaded.sessions[3].process_start_identity == "windows:123456"


def test_registry_rejects_per_session_primary_flag(tmp_path: Path) -> None:
    path = tmp_path / "sessions.json"
    path.write_text(
        json.dumps(
            {
                "primary": 1,
                "sessions": {"1": {"port": 49152, "pid": 12340, "primary": True}},
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(BridgeError) as caught:
        SessionRegistry(path).load()

    assert caught.value.code == "session_registry_invalid"


def test_resolver_uses_primary_when_session_is_omitted(tmp_path: Path) -> None:
    registry = SessionRegistry(tmp_path / "sessions.json")
    registry.save(
        SessionRegistryState(
            primary=3,
            sessions={3: SessionRecord(session=3, port=49154, pid=18744)},
        )
    )
    probe = FakeProbe({49154: _probe_result(pid=18744, port=49154)})
    resolver = SessionResolver(
        registry,
        probe,  # type: ignore[arg-type]
        identity_reader=_identity_reader({18744: "start-a"}),
    )

    resolved = resolver.resolve()

    assert resolved.record.session == 3
    assert resolved.target == HoudiniTarget(host="127.0.0.1", port=49154)
    assert resolved.identity == ProcessIdentity(18744, "start-a")
    assert probe.calls == [49154]


def test_resolver_uses_explicit_session_without_primary_fallback(tmp_path: Path) -> None:
    registry = SessionRegistry(tmp_path / "sessions.json")
    registry.save(
        SessionRegistryState(
            primary=1,
            sessions={
                1: SessionRecord(session=1, port=49152, pid=1001),
                3: SessionRecord(session=3, port=49154, pid=1003),
            },
        )
    )
    probe = FakeProbe({49154: _probe_result(pid=1003, port=49154)})
    resolver = SessionResolver(
        registry,
        probe,  # type: ignore[arg-type]
        identity_reader=_identity_reader({1003: "start-3"}),
    )

    assert resolver.resolve(3).record.session == 3
    assert probe.calls == [49154]


def test_resolver_fails_without_primary_before_dispatch(tmp_path: Path) -> None:
    registry = SessionRegistry(tmp_path / "sessions.json")
    registry.save(SessionRegistryState(primary=None, sessions={}))
    probe = FakeProbe({})
    resolver = SessionResolver(registry, probe)  # type: ignore[arg-type]

    with pytest.raises(BridgeError) as caught:
        resolver.resolve()

    assert caught.value.code == "session_primary_missing"
    assert probe.calls == []


def test_resolver_rejects_dead_registered_pid_before_probe(tmp_path: Path) -> None:
    registry = SessionRegistry(tmp_path / "sessions.json")
    registry.save(
        SessionRegistryState(
            primary=1,
            sessions={1: SessionRecord(session=1, port=49152, pid=1001)},
        )
    )
    probe = FakeProbe({})

    def dead(_pid: int) -> ProcessIdentity:
        raise ProcessLookupError

    resolver = SessionResolver(
        registry,
        probe,  # type: ignore[arg-type]
        identity_reader=dead,
    )

    with pytest.raises(BridgeError) as caught:
        resolver.resolve(1)

    assert caught.value.code == "session_unreachable"
    assert probe.calls == []


def test_resolver_rejects_recycled_recorded_process_identity_before_probe(tmp_path: Path) -> None:
    registry = SessionRegistry(tmp_path / "sessions.json")
    registry.save(
        SessionRegistryState(
            primary=1,
            sessions={
                1: SessionRecord(
                    session=1,
                    port=49152,
                    pid=1001,
                    process_start_identity="old-start",
                )
            },
        )
    )
    probe = FakeProbe({})
    resolver = SessionResolver(
        registry,
        probe,  # type: ignore[arg-type]
        identity_reader=_identity_reader({1001: "new-start"}),
    )

    with pytest.raises(BridgeError) as caught:
        resolver.resolve(1)

    assert caught.value.code == "session_unreachable"
    assert "reused" in (caught.value.detail or "")
    assert probe.calls == []


def test_resolver_rejects_port_that_reports_another_pid(tmp_path: Path) -> None:
    registry = SessionRegistry(tmp_path / "sessions.json")
    registry.save(
        SessionRegistryState(
            primary=1,
            sessions={1: SessionRecord(session=1, port=49152, pid=1001)},
        )
    )
    probe = FakeProbe({49152: _probe_result(pid=2002, port=49152)})
    resolver = SessionResolver(
        registry,
        probe,  # type: ignore[arg-type]
        identity_reader=_identity_reader({1001: "start-a"}),
    )

    with pytest.raises(BridgeError) as caught:
        resolver.resolve(1)

    assert caught.value.code == "session_unreachable"
    assert "different Houdini PID" in (caught.value.detail or "")


def test_session_info_all_uses_exact_public_schema_and_allows_null_file_headless(
    tmp_path: Path,
) -> None:
    registry = SessionRegistry(tmp_path / "sessions.json")
    registry.save(
        SessionRegistryState(
            primary=3,
            sessions={
                3: SessionRecord(session=3, port=49154, pid=1003),
                1: SessionRecord(session=1, port=49152, pid=1001),
            },
        )
    )
    probe = FakeProbe(
        {
            49152: _probe_result(pid=1001, port=49152, file=None, headless=True),
            49154: _probe_result(
                pid=1003,
                port=49154,
                license_name="Apprentice",
                file="C:/project/b.hip",
            ),
        }
    )
    resolver = SessionResolver(
        registry,
        probe,  # type: ignore[arg-type]
        identity_reader=_identity_reader({1001: "a", 1003: "b"}),
    )

    payload = SessionInfoService(registry, resolver).inspect()

    assert payload == {
        "primary": 3,
        "sessions": [
            {
                "session": 1,
                "port": 49152,
                "pid": 1001,
                "version": "22.0.429",
                "license": "Commercial",
                "file": None,
                "headless": True,
            },
            {
                "session": 3,
                "port": 49154,
                "pid": 1003,
                "version": "22.0.429",
                "license": "Apprentice",
                "file": "C:/project/b.hip",
                "headless": False,
            },
        ],
    }


def test_session_info_all_removes_dead_sessions_before_listing(
    tmp_path: Path,
) -> None:
    registry = SessionRegistry(tmp_path / "sessions.json")
    registry.save(
        SessionRegistryState(
            primary=1,
            sessions={
                1: SessionRecord(1, 49152, 1001, "dead-1"),
                2: SessionRecord(2, 49154, 1002, "live-2"),
            },
        )
    )
    probe = FakeProbe({49154: _probe_result(pid=1002, port=49154)})

    def identity(pid: int) -> ProcessIdentity:
        if pid == 1001:
            raise ProcessLookupError(pid)
        return ProcessIdentity(pid, "live-2")

    resolver = SessionResolver(
        registry,
        probe,  # type: ignore[arg-type]
        identity_reader=identity,
    )
    cleanup = SessionStaleCleanupService(registry, identity_reader=identity)

    payload = SessionInfoService(
        registry,
        resolver,
        stale_cleanup=cleanup,
    ).inspect()

    assert payload == {
        "primary": None,
        "sessions": [
            {
                "session": 2,
                "port": 49154,
                "pid": 1002,
                "version": "22.0.429",
                "license": "Commercial",
                "file": "C:/project/test.hip",
                "headless": False,
            }
        ],
    }
    assert set(registry.load().sessions) == {2}
    assert probe.calls == [49154]


def test_session_info_without_sessions_reports_null_primary_without_transport(
    tmp_path: Path,
) -> None:
    registry = SessionRegistry(tmp_path / "sessions.json")
    probe = FakeProbe({})
    resolver = SessionResolver(registry, probe)  # type: ignore[arg-type]

    assert SessionInfoService(registry, resolver).inspect() == {
        "primary": None,
        "sessions": [],
    }
    assert probe.calls == []


def test_session_info_one_adds_only_primary_boolean(tmp_path: Path) -> None:
    registry = SessionRegistry(tmp_path / "sessions.json")
    registry.save(
        SessionRegistryState(
            primary=3,
            sessions={3: SessionRecord(session=3, port=49154, pid=1003)},
        )
    )
    probe = FakeProbe({49154: _probe_result(pid=1003, port=49154)})
    resolver = SessionResolver(
        registry,
        probe,  # type: ignore[arg-type]
        identity_reader=_identity_reader({1003: "b"}),
    )

    assert SessionInfoService(registry, resolver).inspect(3) == {
        "session": 3,
        "primary": True,
        "port": 49154,
        "pid": 1003,
        "version": "22.0.429",
        "license": "Commercial",
        "file": "C:/project/test.hip",
        "headless": False,
    }


def test_session_probe_uses_physical_script_and_private_workspace(
    tmp_path: Path, monkeypatch
) -> None:
    captured: dict[str, object] = {}

    class License:
        def name(self) -> str:
            return "Commercial"

    class HipFile:
        @staticmethod
        def isNewFile() -> bool:
            return True

        @staticmethod
        def path() -> str:
            return "C:/unused.hip"

    fake_hou = SimpleNamespace(
        hipFile=HipFile,
        applicationVersionString=lambda: "22.0.429",
        licenseCategory=lambda: License(),
        isUIAvailable=lambda: False,
        hscript=lambda command: ("49152\n", "") if command == "openport" else ("", ""),
    )
    monkeypatch.setitem(sys.modules, "hou", fake_hou)
    monkeypatch.setattr(os, "getpid", lambda: 42)

    class FakeTransport:
        def execute_script(self, target: HoudiniTarget, script_path: Path) -> TransportResult:
            captured["target"] = target
            captured["script"] = script_path.read_text(encoding="utf-8")
            captured["implementation"] = script_path.with_name(
                "session_probe_impl.py"
            ).read_text(encoding="utf-8")
            namespace = {"__name__": "__main__"}
            exec(
                compile(captured["script"], str(script_path), "exec"),
                namespace,
                namespace,
            )
            assert "__file__" not in namespace
            return TransportResult(stdout="probe stdout\n", stderr="", returncode=0)

    workspaces = TemporaryWorkspaceService(temp_root=tmp_path)
    probe = SessionProbe(lambda: FakeTransport(), workspaces=workspaces)  # type: ignore[arg-type]

    result = probe.inspect(49152)

    assert result.pid == 42
    assert result.file is None
    assert result.headless is True
    assert captured["target"] == HoudiniTarget(host="127.0.0.1", port=49152)
    assert "runpy.run_path" in str(captured["script"])
    assert "import hou" in str(captured["implementation"])
    assert list(workspaces.root.iterdir()) == []


def test_physical_probe_reports_native_session_values(tmp_path: Path, monkeypatch) -> None:
    source = Path(__file__).parents[2] / "src" / "houbridge" / "houdini" / "scripts" / "session" / "probe.py"
    script = tmp_path / "session_probe.py"
    shutil.copyfile(source, script)

    class License:
        def name(self) -> str:
            return "Apprentice"

    class HipFile:
        @staticmethod
        def isNewFile() -> bool:
            return True

        @staticmethod
        def path() -> str:
            return "C:/should-not-be-published/untitled.hip"

    fake_hou = SimpleNamespace(
        hipFile=HipFile,
        applicationVersionString=lambda: "22.0.429",
        licenseCategory=lambda: License(),
        isUIAvailable=lambda: False,
        hscript=lambda command: ("49152\n49154\n", "") if command == "openport" else ("", ""),
    )
    monkeypatch.setitem(sys.modules, "hou", fake_hou)
    monkeypatch.setattr(os, "getpid", lambda: 18744)

    result_path = tmp_path / "session_probe.json"
    namespace = {"__name__": "_houbridge_session_probe_impl"}
    exec(
        compile(script.read_text(encoding="utf-8"), str(script), "exec"),
        namespace,
        namespace,
    )
    assert "__file__" not in namespace
    namespace["main"](result_path)

    payload = json.loads(result_path.read_text(encoding="utf-8"))
    assert payload == {
        "pid": 18744,
        "version": "22.0.429",
        "license": "Apprentice",
        "file": None,
        "headless": True,
        "open_ports": [49152, 49154],
    }


def test_process_identity_reader_is_stable_for_current_process() -> None:
    first = process_identity_for_pid(os.getpid())
    second = process_identity_for_pid(os.getpid())

    assert first.pid == os.getpid()
    assert first == second


def test_session_registry_lock_wait_is_bounded(tmp_path: Path) -> None:
    path = tmp_path / "sessions.json"
    holder = SessionRegistry(path, lock_timeout_seconds=1.0)
    contender = SessionRegistry(path, lock_timeout_seconds=0.05)
    entered = threading.Event()
    release = threading.Event()

    def hold() -> None:
        with holder.locked():
            entered.set()
            assert release.wait(timeout=2)

    thread = threading.Thread(target=hold)
    thread.start()
    assert entered.wait(timeout=2)

    try:
        with pytest.raises(BridgeError) as caught:
            with contender.locked():
                raise AssertionError("contended registry lock must not be acquired")
        assert caught.value.code == "session_registry_lock_timeout"
    finally:
        release.set()
        thread.join(timeout=2)
    assert not thread.is_alive()


def test_session_probe_missing_result_preserves_diagnostics(tmp_path: Path) -> None:
    class MissingResultTransport:
        def execute_script(self, target: HoudiniTarget, script_path: Path) -> TransportResult:
            return TransportResult(
                stdout="Error running Python code:\n",
                stderr="NameError: __file__ is not defined\n",
                returncode=0,
            )

    workspaces = TemporaryWorkspaceService(temp_root=tmp_path)
    probe = SessionProbe(
        lambda: MissingResultTransport(),  # type: ignore[arg-type]
        workspaces=workspaces,
    )

    with pytest.raises(BridgeError) as caught:
        probe.inspect(49152)

    assert caught.value.code == "session_probe_missing"
    diagnostics = next(workspaces.root.iterdir())
    assert f"probe_diagnostics={diagnostics}" in (caught.value.detail or "")
    assert (diagnostics / "session_probe.py").is_file()
    assert json.loads((diagnostics / "probe.context.json").read_text(encoding="utf-8")) == {
        "host": "127.0.0.1",
        "port": 49152,
    }
    assert (diagnostics / "hcommand.stdout.log").read_text(encoding="utf-8") == (
        "Error running Python code:\n"
    )
    assert (diagnostics / "hcommand.stderr.log").read_text(encoding="utf-8") == (
        "NameError: __file__ is not defined\n"
    )
    assert "session_probe_missing" in (diagnostics / "probe.error.txt").read_text(
        encoding="utf-8"
    )
