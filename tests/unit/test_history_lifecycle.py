from __future__ import annotations

import runpy
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest


STATE_MODULE = "_houbridge_history_scene_lifecycle_v1"
SCRIPT = (
    Path(__file__).parents[2]
    / "src"
    / "houbridge"
    / "houdini"
    / "scripts"
    / "history"
    / "lifecycle.py"
)


class FakeHipFile:
    def __init__(self) -> None:
        self.callbacks: list[object] = []

    def addEventCallback(self, callback) -> None:
        self.callbacks.append(callback)

    def emit(self, event_type) -> None:
        for callback in tuple(self.callbacks):
            callback(event_type)


@pytest.fixture(autouse=True)
def _clear_history_lifecycle_state(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delitem(sys.modules, STATE_MODULE, raising=False)


def _load_runtime(monkeypatch: pytest.MonkeyPatch):
    hip_file = FakeHipFile()
    event_types = SimpleNamespace(
        AfterLoad=object(),
        AfterClear=object(),
        AfterMerge=object(),
        AfterSave=object(),
    )
    hou = types.ModuleType("hou")
    hou.hipFile = hip_file
    hou.hipFileEventType = event_types
    monkeypatch.setitem(sys.modules, "hou", hou)
    return runpy.run_path(str(SCRIPT)), hip_file, event_types


def test_after_load_and_clear_destroy_current_database_and_advance_generation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, hip_file, events = _load_runtime(monkeypatch)
    database = tmp_path / "history.db"
    sidecars = [Path(str(database) + suffix) for suffix in ("-wal", "-shm", "-journal")]

    assert runtime["install"](str(database)) == 0
    assert len(hip_file.callbacks) == 1

    for path in (database, *sidecars):
        path.write_bytes(b"history")
    hip_file.emit(events.AfterLoad)
    assert runtime["current_generation"](str(database)) == 1
    assert not any(path.exists() for path in (database, *sidecars))

    database.write_bytes(b"new history")
    hip_file.emit(events.AfterClear)
    assert runtime["current_generation"](str(database)) == 2
    assert not database.exists()


def test_merge_and_save_do_not_reset_history(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, hip_file, events = _load_runtime(monkeypatch)
    database = tmp_path / "history.db"
    database.write_bytes(b"keep")
    runtime["install"](str(database))

    hip_file.emit(events.AfterMerge)
    hip_file.emit(events.AfterSave)

    assert database.read_bytes() == b"keep"
    assert runtime["current_generation"](str(database)) == 0


def test_reinstall_reuses_one_process_local_callback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, hip_file, _events = _load_runtime(monkeypatch)
    database = tmp_path / "history.db"

    assert runtime["install"](str(database)) == 0
    runtime_again = runpy.run_path(str(SCRIPT))
    assert runtime_again["install"](str(database)) == 0

    assert len(hip_file.callbacks) == 1
