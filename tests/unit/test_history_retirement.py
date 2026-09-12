from __future__ import annotations

from pathlib import Path

from houbridge.history import HistoryRetirementService, history_session_key
from houbridge.paths import GlobalDataPaths
from houbridge.process_coordination import ProcessIdentity
from houbridge.session.registry import SessionRecord, SessionRegistry, SessionRegistryState
from houbridge.session.stale import SessionStaleCleanupService


def test_stale_session_cleanup_retires_only_exact_stale_history(tmp_path: Path) -> None:
    paths = GlobalDataPaths.from_data_dir(tmp_path / "data")
    registry = SessionRegistry(paths.sessions_registry)
    live_identity = ProcessIdentity(1001, "live-start")
    stale_identity = ProcessIdentity(1002, "old-start")
    reused_identity = ProcessIdentity(1002, "new-start")
    registry.save(
        SessionRegistryState(
            primary=2,
            sessions={
                1: SessionRecord(1, 49151, live_identity.pid, live_identity.process_start_identity),
                2: SessionRecord(2, 49152, stale_identity.pid, stale_identity.process_start_identity),
            },
        )
    )

    live_dir = paths.history_session(history_session_key(live_identity)).session_directory
    stale_dir = paths.history_session(history_session_key(stale_identity)).session_directory
    live_dir.mkdir(parents=True)
    stale_dir.mkdir(parents=True)
    (live_dir / "history.db").write_bytes(b"live")
    (stale_dir / "history.db").write_bytes(b"stale")
    retirement = HistoryRetirementService(paths)

    def identity_reader(pid: int) -> ProcessIdentity:
        if pid == 1001:
            return live_identity
        if pid == 1002:
            return reused_identity
        raise ProcessLookupError(pid)

    cleanup = SessionStaleCleanupService(
        registry,
        identity_reader=identity_reader,
        on_stale=lambda record: retirement.retire(
            ProcessIdentity(record.pid, record.process_start_identity or "missing")
        ),
    )
    state = cleanup.cleanup()

    assert set(state.sessions) == {1}
    assert state.primary is None
    assert live_dir.exists()
    assert not stale_dir.exists()
    assert not paths.history_session(history_session_key(reused_identity)).session_directory.exists()


def test_stale_cleanup_commits_registry_before_retirement_failure(tmp_path: Path) -> None:
    paths = GlobalDataPaths.from_data_dir(tmp_path / "data")
    registry = SessionRegistry(paths.sessions_registry)
    stale = SessionRecord(1, 49151, 1001, "old-start")
    registry.save(SessionRegistryState(primary=1, sessions={1: stale}))
    observed_states: list[SessionRegistryState] = []

    def identity_reader(pid: int) -> ProcessIdentity:
        raise ProcessLookupError(pid)

    def failing_retirement(record: SessionRecord) -> None:
        observed_states.append(registry.load())
        raise PermissionError(f"locked History for session {record.session}")

    cleanup = SessionStaleCleanupService(
        registry,
        identity_reader=identity_reader,
        on_stale=failing_retirement,
    )

    state = cleanup.cleanup()

    assert state == SessionRegistryState.empty()
    assert registry.load() == SessionRegistryState.empty()
    assert observed_states == [SessionRegistryState.empty()]


def test_history_retirement_is_best_effort_when_directory_is_locked(
    tmp_path: Path,
    monkeypatch,
) -> None:
    paths = GlobalDataPaths.from_data_dir(tmp_path / "data")
    identity = ProcessIdentity(1002, "old-start")
    session_dir = paths.history_session(history_session_key(identity)).session_directory
    session_dir.mkdir(parents=True)
    (session_dir / "history.db").write_bytes(b"stale")

    def fail_remove(_path: Path) -> None:
        raise PermissionError("simulated locked History directory")

    monkeypatch.setattr("houbridge.history.retirement.shutil.rmtree", fail_remove)

    assert HistoryRetirementService(paths).retire(identity) is False
    assert session_dir.exists()
