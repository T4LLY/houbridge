from __future__ import annotations

from pathlib import Path
import threading
import time

import pytest

import houbridge.process_coordination as coordination
from houbridge.process_coordination import (
    InterprocessFileLock,
    InterprocessFileLockTimeout,
    ManagedExecutionLock,
    ManagedExecutionLockTimeout,
    ProcessIdentity,
)


def _use_test_coordination_root(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> Path:
    root = tmp_path / "user-runtime" / "houbridge" / "coordination"
    monkeypatch.setattr(coordination, "coordination_directory", lambda: root)
    return root


def test_process_identity_normalizes_pid_and_start_identity() -> None:
    assert ProcessIdentity.normalize(1200, 987654) == ProcessIdentity(
        pid=1200,
        process_start_identity="987654",
    )
    assert ProcessIdentity.normalize(1200, "  boot-42  ") == ProcessIdentity(
        pid=1200,
        process_start_identity="boot-42",
    )


@pytest.mark.parametrize(
    ("pid", "start_identity"),
    [
        (0, "1"),
        (-1, "1"),
        (True, "1"),
        (1, ""),
        (1, "   "),
    ],
)
def test_process_identity_rejects_invalid_values(
    pid: int,
    start_identity: str,
) -> None:
    with pytest.raises((TypeError, ValueError)):
        ProcessIdentity(pid=pid, process_start_identity=start_identity)


def test_coordination_directory_is_platform_runtime_not_configured_data_dir(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runtime = tmp_path / "platform-runtime" / "houbridge"
    monkeypatch.setattr(
        coordination,
        "user_runtime_path",
        lambda appname, ensure_exists=False: runtime,
    )

    assert coordination.coordination_directory() == runtime / "coordination"


def test_interprocess_file_lock_serializes_same_path(tmp_path: Path) -> None:
    path = tmp_path / "registry.lock"
    holder_lock = InterprocessFileLock(poll_interval_seconds=0.01)
    contender_lock = InterprocessFileLock(poll_interval_seconds=0.01)
    entered = threading.Event()
    release = threading.Event()

    def holder() -> None:
        with holder_lock.acquire(path):
            entered.set()
            assert release.wait(timeout=2)

    thread = threading.Thread(target=holder)
    thread.start()
    assert entered.wait(timeout=2)

    with pytest.raises(InterprocessFileLockTimeout):
        with contender_lock.acquire(path, timeout_seconds=0.05):
            raise AssertionError("same lock path must not overlap")

    release.set()
    thread.join(timeout=2)
    assert not thread.is_alive()

    with contender_lock.acquire(path, timeout_seconds=0.05):
        pass

def test_same_process_incarnation_is_serialized(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _use_test_coordination_root(monkeypatch, tmp_path)
    identity = ProcessIdentity.normalize(1000, "start-a")
    lock = ManagedExecutionLock(poll_interval_seconds=0.01)
    entered = threading.Event()
    release = threading.Event()

    def holder() -> None:
        with lock.acquire(identity):
            entered.set()
            assert release.wait(timeout=2)

    thread = threading.Thread(target=holder)
    thread.start()
    assert entered.wait(timeout=2)

    with pytest.raises(ManagedExecutionLockTimeout):
        with lock.acquire(identity, timeout_seconds=0.05):
            raise AssertionError("same process incarnation must not overlap")

    release.set()
    thread.join(timeout=2)
    assert not thread.is_alive()


def test_different_processes_can_overlap(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _use_test_coordination_root(monkeypatch, tmp_path)
    lock = ManagedExecutionLock(poll_interval_seconds=0.01)
    first = ProcessIdentity.normalize(1000, "start-a")
    second = ProcessIdentity.normalize(2000, "start-b")

    with lock.acquire(first):
        with lock.acquire(second, timeout_seconds=0.05):
            pass


def test_pid_reuse_with_new_incarnation_is_independent(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = _use_test_coordination_root(monkeypatch, tmp_path)
    lock = ManagedExecutionLock(poll_interval_seconds=0.01)
    old = ProcessIdentity.normalize(1000, "start-old")
    reused = ProcessIdentity.normalize(1000, "start-new")

    with lock.acquire(old):
        with lock.acquire(reused, timeout_seconds=0.05):
            pass

    lock_files = list((root / "managed-execution").glob("pid-1000-*.lock"))
    assert len(lock_files) == 2


def test_lock_is_released_after_body_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _use_test_coordination_root(monkeypatch, tmp_path)
    identity = ProcessIdentity.normalize(777, "start")
    lock = ManagedExecutionLock(poll_interval_seconds=0.01)

    with pytest.raises(RuntimeError, match="boom"):
        with lock.acquire(identity):
            raise RuntimeError("boom")

    with lock.acquire(identity, timeout_seconds=0.05):
        pass
