from __future__ import annotations

import errno
import os
import sys
import time
import types
from contextlib import contextmanager
from pathlib import Path


_STATE_MODULE_NAME = "_houbridge_history_scene_lifecycle_v1"
_DEFAULT_LOCK_TIMEOUT_SECONDS = 120.0
_LOCK_POLL_INTERVAL_SECONDS = 0.05


class _LockTimeout(TimeoutError):
    pass


def install(
    database_path_value: str,
    database_lock_path_value: str,
    lock_timeout_seconds_value: float = _DEFAULT_LOCK_TIMEOUT_SECONDS,
) -> int:
    """Bind one process-local callback and return the current scene generation."""

    import hou

    database_path = str(Path(database_path_value).resolve())
    database_lock_path = str(Path(database_lock_path_value).resolve())
    lock_timeout_seconds = _positive_timeout(lock_timeout_seconds_value)
    state = sys.modules.get(_STATE_MODULE_NAME)
    if state is None:
        state = types.ModuleType(_STATE_MODULE_NAME)
        state.database_path = database_path
        state.database_lock_path = database_lock_path
        state.lock_timeout_seconds = lock_timeout_seconds
        state.generation = 0

        def on_hip_event(event_type) -> None:
            if event_type not in (
                hou.hipFileEventType.AfterLoad,
                hou.hipFileEventType.AfterClear,
            ):
                return
            state.generation += 1
            _destroy_database(
                Path(state.database_path),
                Path(state.database_lock_path),
                float(state.lock_timeout_seconds),
            )

        state.callback = on_hip_event
        sys.modules[_STATE_MODULE_NAME] = state
        hou.hipFile.addEventCallback(on_hip_event)
    elif (
        getattr(state, "database_path", None) != database_path
        or getattr(state, "database_lock_path", None) != database_lock_path
    ):
        raise RuntimeError(
            "History lifecycle is already bound to different storage for this Houdini process."
        )
    else:
        # The timeout is runtime policy, not scene identity. Let later managed
        # invocations refresh it without installing another callback.
        state.lock_timeout_seconds = lock_timeout_seconds

    return int(state.generation)


def current_generation(database_path_value: str) -> int:
    database_path = str(Path(database_path_value).resolve())
    state = sys.modules.get(_STATE_MODULE_NAME)
    if state is None or getattr(state, "database_path", None) != database_path:
        raise RuntimeError("History lifecycle has not been installed for this database.")
    return int(state.generation)


def _destroy_database(
    database_path: Path,
    database_lock_path: Path,
    lock_timeout_seconds: float,
) -> None:
    # Publish the reset intent before waiting. If the Houdini UI cannot acquire
    # the lock within its bounded wait, the next host-side History connection
    # consumes this marker under the same lock before it can open/create the DB.
    reset_path = database_lock_path.with_suffix(".reset")
    _mark_reset_pending(reset_path)
    try:
        with _database_lock(database_lock_path, timeout_seconds=lock_timeout_seconds):
            _consume_pending_reset(database_path, reset_path)
    except _LockTimeout:
        # Scene replacement must not freeze Houdini's UI indefinitely. Leaving
        # the marker in place prevents the old scene database from being reused.
        return


def _mark_reset_pending(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        handle.flush()
        os.fsync(handle.fileno())


def _consume_pending_reset(database_path: Path, reset_path: Path) -> None:
    if not reset_path.is_file():
        return
    for path in (
        database_path,
        Path(str(database_path) + "-wal"),
        Path(str(database_path) + "-shm"),
        Path(str(database_path) + "-journal"),
    ):
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass
    try:
        os.unlink(reset_path)
    except FileNotFoundError:
        pass


@contextmanager
def _database_lock(path: Path, *, timeout_seconds: float):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        _ensure_lock_byte(handle)
        _lock(handle, timeout_seconds=timeout_seconds)
        try:
            yield
        finally:
            _unlock(handle)


def _ensure_lock_byte(handle) -> None:
    handle.seek(0, os.SEEK_END)
    if handle.tell() == 0:
        handle.write(b"\0")
        handle.flush()
    handle.seek(0)


def _positive_timeout(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("lock_timeout_seconds must be a finite positive number")
    parsed = float(value)
    if parsed <= 0 or parsed != parsed or parsed in {float("inf"), float("-inf")}:
        raise ValueError("lock_timeout_seconds must be a finite positive number")
    return parsed


def _wait_for_lock(try_lock, *, timeout_seconds: float) -> None:
    deadline = time.monotonic() + timeout_seconds
    while True:
        try:
            try_lock()
            return
        except BlockingIOError:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise _LockTimeout from None
            time.sleep(min(_LOCK_POLL_INTERVAL_SECONDS, remaining))


if os.name == "nt":
    import msvcrt

    def _lock(handle, *, timeout_seconds: float) -> None:
        def try_lock() -> None:
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                if exc.errno in {errno.EACCES, errno.EAGAIN, errno.EDEADLK, errno.EPERM}:
                    raise BlockingIOError from exc
                raise

        _wait_for_lock(try_lock, timeout_seconds=timeout_seconds)

    def _unlock(handle) -> None:
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)

else:
    import fcntl

    def _lock(handle, *, timeout_seconds: float) -> None:
        def try_lock() -> None:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                if exc.errno in {errno.EACCES, errno.EAGAIN}:
                    raise BlockingIOError from exc
                raise

        _wait_for_lock(try_lock, timeout_seconds=timeout_seconds)

    def _unlock(handle) -> None:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
