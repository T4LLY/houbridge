from __future__ import annotations

from pathlib import Path

import pytest

from houbridge.errors import BridgeError
from houbridge.process_coordination import ProcessIdentity
from houbridge.session.attach import SessionAttachService
from houbridge.session.probe import SessionProbeResult
from houbridge.session.registry import SessionRecord, SessionRegistry, SessionRegistryState


class FakeProbe:
    def __init__(self, results: list[SessionProbeResult]) -> None:
        self.results = list(results)
        self.calls: list[int] = []

    def inspect(self, port: int) -> SessionProbeResult:
        self.calls.append(port)
        if len(self.results) == 1:
            return self.results[0]
        return self.results.pop(0)


def _probe_result(*, pid: int = 18744, port: int = 49153) -> SessionProbeResult:
    return SessionProbeResult(
        pid=pid,
        version="22.0.429",
        license="Commercial",
        file=None,
        headless=False,
        open_ports=(port,),
    )


def _identity(pid: int) -> ProcessIdentity:
    return ProcessIdentity(pid, f"start-{pid}")


def test_attach_first_existing_houdini_registers_session_one_and_primary(tmp_path: Path) -> None:
    registry = SessionRegistry(tmp_path / "sessions.json")
    probe = FakeProbe([_probe_result(), _probe_result()])

    payload = SessionAttachService(
        registry,
        probe,  # type: ignore[arg-type]
        identity_reader=_identity,
    ).attach(49153)

    assert payload == {"session": 1, "port": 49153, "pid": 18744}
    state = registry.load()
    assert state.primary == 1
    assert state.sessions[1] == SessionRecord(1, 49153, 18744, "start-18744")
    assert probe.calls == [49153, 49153]


def test_attach_additional_session_preserves_existing_primary(tmp_path: Path) -> None:
    registry = SessionRegistry(tmp_path / "sessions.json")
    registry.save(
        SessionRegistryState(
            primary=1,
            sessions={1: SessionRecord(1, 49152, 1001, "start-1001")},
        )
    )
    probe = FakeProbe([_probe_result(pid=2002), _probe_result(pid=2002)])

    payload = SessionAttachService(
        registry,
        probe,  # type: ignore[arg-type]
        identity_reader=_identity,
        port_status_reader=lambda _port: True,
    ).attach(49153)

    assert payload == {"session": 2, "port": 49153, "pid": 2002}
    state = registry.load()
    assert state.primary == 1
    assert set(state.sessions) == {1, 2}


def test_attach_after_all_registered_sessions_are_stale_becomes_primary(tmp_path: Path) -> None:
    registry = SessionRegistry(tmp_path / "sessions.json")
    registry.save(
        SessionRegistryState(
            primary=1,
            sessions={1: SessionRecord(1, 49152, 1001, "old-start")},
        )
    )
    probe = FakeProbe([_probe_result(pid=2002), _probe_result(pid=2002)])

    def identity(pid: int) -> ProcessIdentity:
        if pid == 1001:
            raise ProcessLookupError(pid)
        return _identity(pid)

    payload = SessionAttachService(
        registry,
        probe,  # type: ignore[arg-type]
        identity_reader=identity,
    ).attach(49153)

    assert payload["session"] == 1
    state = registry.load()
    assert state.primary == 1
    assert state.sessions[1].pid == 2002


def test_attach_does_not_create_primary_when_other_live_sessions_remain(tmp_path: Path) -> None:
    registry = SessionRegistry(tmp_path / "sessions.json")
    registry.save(
        SessionRegistryState(
            primary=None,
            sessions={1: SessionRecord(1, 49152, 1001, "start-1001")},
        )
    )
    probe = FakeProbe([_probe_result(pid=2002), _probe_result(pid=2002)])

    SessionAttachService(
        registry,
        probe,  # type: ignore[arg-type]
        identity_reader=_identity,
        port_status_reader=lambda _port: True,
    ).attach(49153)

    assert registry.load().primary is None


def test_attach_same_registered_target_is_idempotent(tmp_path: Path) -> None:
    registry = SessionRegistry(tmp_path / "sessions.json")
    registry.save(
        SessionRegistryState(
            primary=1,
            sessions={1: SessionRecord(1, 49153, 18744, "start-18744")},
        )
    )
    probe = FakeProbe([_probe_result(), _probe_result()])

    payload = SessionAttachService(
        registry,
        probe,  # type: ignore[arg-type]
        identity_reader=_identity,
        port_status_reader=lambda _port: True,
    ).attach(49153)

    assert payload == {"session": 1, "port": 49153, "pid": 18744}
    assert set(registry.load().sessions) == {1}


def test_attach_rejects_second_port_for_already_registered_process(tmp_path: Path) -> None:
    registry = SessionRegistry(tmp_path / "sessions.json")
    registry.save(
        SessionRegistryState(
            primary=1,
            sessions={1: SessionRecord(1, 49152, 18744, "start-18744")},
        )
    )
    probe = FakeProbe([_probe_result(), _probe_result()])

    with pytest.raises(BridgeError) as caught:
        SessionAttachService(
            registry,
            probe,  # type: ignore[arg-type]
            identity_reader=_identity,
            port_status_reader=lambda _port: True,
        ).attach(49153)

    assert caught.value.code == "session_already_registered"
    assert set(registry.load().sessions) == {1}


def test_attach_rejects_port_not_reported_by_houdini(tmp_path: Path) -> None:
    registry = SessionRegistry(tmp_path / "sessions.json")
    probe = FakeProbe([_probe_result(port=49154)])

    with pytest.raises(BridgeError) as caught:
        SessionAttachService(
            registry,
            probe,  # type: ignore[arg-type]
            identity_reader=_identity,
        ).attach(49153)

    assert caught.value.code == "session_attach_unreachable"
    assert not registry.path.exists()


def test_attach_rejects_target_that_changes_pid_during_validation(tmp_path: Path) -> None:
    registry = SessionRegistry(tmp_path / "sessions.json")
    probe = FakeProbe([
        _probe_result(pid=1001),
        _probe_result(pid=1002),
    ])

    with pytest.raises(BridgeError) as caught:
        SessionAttachService(
            registry,
            probe,  # type: ignore[arg-type]
            identity_reader=_identity,
        ).attach(49153)

    assert caught.value.code == "session_attach_unreachable"
    assert not registry.path.exists()
