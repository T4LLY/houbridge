from __future__ import annotations

from pathlib import Path

from houbridge.process_coordination import ProcessIdentity
from houbridge.session.registry import SessionRecord, SessionRegistry, SessionRegistryState
from houbridge.session.stale import SessionStaleCleanupService, _local_port_status


def _registry_with_live_process(tmp_path: Path) -> tuple[SessionRegistry, SessionRecord]:
    registry = SessionRegistry(tmp_path / "sessions.json")
    record = SessionRecord(1, 49152, 1001, "start-1")
    registry.save(SessionRegistryState(primary=1, sessions={1: record}))
    return registry, record


def _identity_reader(pid: int) -> ProcessIdentity:
    return ProcessIdentity(pid, "start-1")


def test_stale_cleanup_removes_live_pid_when_registered_port_is_refused(tmp_path: Path) -> None:
    registry, record = _registry_with_live_process(tmp_path)
    retired: list[SessionRecord] = []
    cleanup = SessionStaleCleanupService(
        registry,
        identity_reader=_identity_reader,
        port_status_reader=lambda _port: False,
        on_stale=retired.append,
    )

    state = cleanup.cleanup()

    assert state == SessionRegistryState.empty()
    assert registry.load() == SessionRegistryState.empty()
    assert retired == [record]


def test_stale_cleanup_keeps_live_pid_when_registered_port_accepts(tmp_path: Path) -> None:
    registry, record = _registry_with_live_process(tmp_path)
    cleanup = SessionStaleCleanupService(
        registry,
        identity_reader=_identity_reader,
        port_status_reader=lambda _port: True,
    )

    state = cleanup.cleanup()

    assert state.primary == 1
    assert state.sessions == {1: record}


def test_stale_cleanup_keeps_live_pid_when_port_state_is_inconclusive(tmp_path: Path) -> None:
    registry, record = _registry_with_live_process(tmp_path)
    cleanup = SessionStaleCleanupService(
        registry,
        identity_reader=_identity_reader,
        port_status_reader=lambda _port: None,
    )

    state = cleanup.cleanup()

    assert state.primary == 1
    assert state.sessions == {1: record}


class _ConnectedSocket:
    def __enter__(self) -> "_ConnectedSocket":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None


def test_local_port_status_reports_open_when_tcp_connect_succeeds(monkeypatch) -> None:
    monkeypatch.setattr(
        "houbridge.session.stale.socket.create_connection",
        lambda *args, **kwargs: _ConnectedSocket(),
    )

    assert _local_port_status(49152) is True


def test_local_port_status_reports_closed_only_for_connection_refused(monkeypatch) -> None:
    def refused(*args, **kwargs):
        raise ConnectionRefusedError("closed")

    monkeypatch.setattr("houbridge.session.stale.socket.create_connection", refused)

    assert _local_port_status(49152) is False


def test_local_port_status_treats_timeout_as_inconclusive(monkeypatch) -> None:
    def timed_out(*args, **kwargs):
        raise TimeoutError("busy or delayed")

    monkeypatch.setattr("houbridge.session.stale.socket.create_connection", timed_out)

    assert _local_port_status(49152) is None


def test_local_port_status_treats_other_socket_error_as_inconclusive(monkeypatch) -> None:
    def failed(*args, **kwargs):
        raise OSError("temporary socket failure")

    monkeypatch.setattr("houbridge.session.stale.socket.create_connection", failed)

    assert _local_port_status(49152) is None
