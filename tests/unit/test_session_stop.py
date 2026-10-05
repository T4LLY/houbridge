from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from houbridge.errors import BridgeError
from houbridge.houdini.transport import HoudiniTarget
from houbridge.process_coordination import ProcessIdentity
from houbridge.session.registry import SessionRecord, SessionRegistry, SessionRegistryState
from houbridge.session.stop import SessionStopService
from houbridge.temporary_workspace import TemporaryWorkspaceService


class _Resolver:
    def __init__(self, record: SessionRecord) -> None:
        self.record = record
        self.calls: list[int] = []

    def resolve(self, session: int):
        self.calls.append(session)
        return SimpleNamespace(
            record=self.record,
            target=HoudiniTarget(host="127.0.0.1", port=self.record.port),
        )


class _Transport:
    def __init__(self, payload: dict[str, object], *, error: BridgeError | None = None) -> None:
        self.payload = payload
        self.error = error
        self.calls = 0

    def execute_script(self, target: HoudiniTarget, runner: Path):
        self.calls += 1
        (runner.parent / "result.json").write_text(
            json.dumps(self.payload),
            encoding="utf-8",
        )
        if self.error is not None:
            raise self.error
        return SimpleNamespace(stdout="", stderr="", returncode=0)


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def _registry(tmp_path: Path, *, primary: int | None = 1) -> tuple[SessionRegistry, SessionRecord]:
    registry = SessionRegistry(tmp_path / "sessions.json")
    record = SessionRecord(1, 49151, 1001, "process-1")
    registry.save(SessionRegistryState(primary=primary, sessions={1: record}))
    return registry, record


def _service(
    tmp_path: Path,
    registry: SessionRegistry,
    record: SessionRecord,
    transport: _Transport,
    *,
    identity_reader,
    clock: _Clock | None = None,
) -> SessionStopService:
    clock = clock or _Clock()
    return SessionStopService(
        registry,
        _Resolver(record),
        transport,  # type: ignore[arg-type]
        shutdown_timeout_seconds=2.0,
        poll_interval_seconds=0.25,
        identity_reader=identity_reader,
        workspaces=TemporaryWorkspaceService(temp_root=tmp_path / "tmp"),
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )


def test_stop_removes_registry_only_after_process_exit(tmp_path: Path) -> None:
    registry, record = _registry(tmp_path)
    transport = _Transport({"ok": True, "status": "stopping", "path": "C:/scene.hip"})

    def exited(_pid: int) -> ProcessIdentity:
        raise ProcessLookupError(record.pid)

    result = _service(
        tmp_path,
        registry,
        record,
        transport,
        identity_reader=exited,
    ).stop(1)

    assert result == {"stopped": 1}
    state = registry.load()
    assert state.primary is None
    assert state.sessions == {}


def test_stop_refuses_unsaved_changes_without_registry_mutation(tmp_path: Path) -> None:
    registry, record = _registry(tmp_path)
    original = registry.load()
    transport = _Transport(
        {
            "ok": False,
            "code": "session_unsaved_changes",
            "message": "Houdini session has unsaved HIP changes.",
            "detail": "path=C:/scene.hip",
        }
    )

    with pytest.raises(BridgeError) as exc_info:
        _service(
            tmp_path,
            registry,
            record,
            transport,
            identity_reader=lambda _pid: pytest.fail("exit wait must not start"),
        ).stop(1)

    assert exc_info.value.code == "session_unsaved_changes"
    assert registry.load() == original


def test_stop_discard_is_forwarded_to_houdini_request(tmp_path: Path) -> None:
    registry, record = _registry(tmp_path)

    class _InspectingTransport(_Transport):
        def __init__(self) -> None:
            super().__init__({"ok": True, "status": "stopping", "path": "C:/scene.hip"})
            self.request: dict[str, object] | None = None

        def execute_script(self, target: HoudiniTarget, runner: Path):
            self.request = json.loads((runner.parent / "request.json").read_text(encoding="utf-8"))
            return super().execute_script(target, runner)

    transport = _InspectingTransport()

    def exited(_pid: int) -> ProcessIdentity:
        raise ProcessLookupError(record.pid)

    result = _service(
        tmp_path,
        registry,
        record,
        transport,
        identity_reader=exited,
    ).stop(1, discard=True)

    assert result == {"stopped": 1}
    assert transport.request is not None
    assert transport.request["discard"] is True


def test_stop_accepts_hcommand_disconnect_after_stopping_marker(tmp_path: Path) -> None:
    registry, record = _registry(tmp_path)
    transport = _Transport(
        {"ok": True, "status": "stopping", "path": "C:/scene.hip"},
        error=BridgeError("houdini_transport_failed", "openport closed during exit"),
    )

    def exited(_pid: int) -> ProcessIdentity:
        raise ProcessLookupError(record.pid)

    assert _service(
        tmp_path,
        registry,
        record,
        transport,
        identity_reader=exited,
    ).stop(1) == {"stopped": 1}


def test_stop_timeout_keeps_registry_and_does_not_force_kill(tmp_path: Path) -> None:
    registry, record = _registry(tmp_path)
    original = registry.load()
    transport = _Transport({"ok": True, "status": "stopping", "path": "C:/scene.hip"})
    clock = _Clock()

    with pytest.raises(BridgeError) as exc_info:
        _service(
            tmp_path,
            registry,
            record,
            transport,
            identity_reader=lambda pid: ProcessIdentity(pid, "process-1"),
            clock=clock,
        ).stop(1)

    assert exc_info.value.code == "session_stop_timeout"
    assert registry.load() == original


def test_stop_treats_pid_reuse_as_original_process_exit(tmp_path: Path) -> None:
    registry, record = _registry(tmp_path)
    transport = _Transport({"ok": True, "status": "stopping", "path": "C:/scene.hip"})

    result = _service(
        tmp_path,
        registry,
        record,
        transport,
        identity_reader=lambda pid: ProcessIdentity(pid, "replacement-process"),
    ).stop(1)

    assert result == {"stopped": 1}
    assert registry.load().sessions == {}


def test_stop_does_not_remove_replacement_registry_record(tmp_path: Path) -> None:
    registry, record = _registry(tmp_path)
    replacement = SessionRecord(1, 49222, 2002, "process-2")

    class _ReplacingTransport(_Transport):
        def execute_script(self, target: HoudiniTarget, runner: Path):
            result = super().execute_script(target, runner)
            registry.save(SessionRegistryState(primary=1, sessions={1: replacement}))
            return result

    transport = _ReplacingTransport({"ok": True, "status": "stopping", "path": "C:/scene.hip"})

    def exited(_pid: int) -> ProcessIdentity:
        raise ProcessLookupError(record.pid)

    result = _service(
        tmp_path,
        registry,
        record,
        transport,
        identity_reader=exited,
    ).stop(1)

    assert result == {"stopped": 1}
    assert registry.load().sessions[1] == replacement


def test_stop_rejects_non_positive_session_before_resolution(tmp_path: Path) -> None:
    registry, record = _registry(tmp_path)
    transport = _Transport({"ok": True, "status": "stopping", "path": "C:/scene.hip"})

    with pytest.raises(BridgeError) as exc_info:
        _service(
            tmp_path,
            registry,
            record,
            transport,
            identity_reader=lambda pid: ProcessIdentity(pid, "process-1"),
        ).stop(0)

    assert exc_info.value.code == "invalid_session"
    assert transport.calls == 0
