from __future__ import annotations

import errno
import os
import sys
import time
import types
from contextlib import contextmanager
from pathlib import Path


_STATE_MODULE_NAME = "_houbridge_history_scene_lifecycle_v1"


def install(database_path_value: str, database_lock_path_value: str) -> int:
    """Bind one process-local callback and return the current scene generation."""

    import hou

    database_path = str(Path(database_path_value).resolve())
    database_lock_path = str(Path(database_lock_path_value).resolve())
    state = sys.modules.get(_STATE_MODULE_NAME)
    if state is None:
        state = types.ModuleType(_STATE_MODULE_NAME)
        state.database_path = database_path
        state.database_lock_path = database_lock_path
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

    return int(state.generation)


def current_generation(database_path_value: str) -> int:
    database_path = str(Path(database_path_value).resolve())
    state = sys.modules.get(_STATE_MODULE_NAME)
    if state is None or getattr(state, "database_path", None) != database_path:
        raise RuntimeError("History lifecycle has not been installed for this database.")
    return int(state.generation)


def _destroy_database(database_path: Path, database_lock_path: Path) -> None:
    # History readers/writers use the same OS-level lock. Waiting here prevents
    # unlinking a SQLite database while another process still owns a connection.
    with _database_lock(database_lock_path):
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


@contextmanager
def _database_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        _ensure_lock_byte(handle)
        _lock(handle)
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


if os.name == "nt":
    import msvcrt

    def _lock(handle) -> None:
        while True:
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                return
            except OSError as exc:
                if exc.errno not in {errno.EACCES, errno.EAGAIN, errno.EDEADLK, errno.EPERM}:
                    raise
                time.sleep(0.05)

    def _unlock(handle) -> None:
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)

else:
    import fcntl

    def _lock(handle) -> None:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)

    def _unlock(handle) -> None:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
