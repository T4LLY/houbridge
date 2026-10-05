from __future__ import annotations

import json
import runpy
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


class _SystemExit(BaseException):
    pass


class _HipFile:
    def __init__(self, *, dirty: bool) -> None:
        self.dirty = dirty
        self.save_calls = 0

    def path(self) -> str:
        return "C:/scene.hip"

    def hasUnsavedChanges(self) -> bool:
        return self.dirty

    def save(self) -> None:
        self.save_calls += 1


def _run(
    tmp_path: Path,
    monkeypatch,
    *,
    dirty: bool,
    ui_available: bool = True,
    discard: bool = False,
    exit_type: type[BaseException] = _SystemExit,
):
    hip_file = _HipFile(dirty=dirty)
    exit_calls: list[tuple[int, bool]] = []

    def exit_houdini(code: int, *, suppress_save_prompt: bool = False) -> None:
        exit_calls.append((code, suppress_save_prompt))
        raise exit_type(code)

    fake_hou = SimpleNamespace(
        hipFile=hip_file,
        isUIAvailable=lambda: ui_available,
        exit=exit_houdini,
        SystemExit=_SystemExit,
    )
    monkeypatch.setitem(sys.modules, "hou", fake_hou)

    script = (
        Path(__file__).parents[2]
        / "src"
        / "houbridge"
        / "houdini"
        / "scripts"
        / "session"
        / "stop.py"
    )
    runtime = runpy.run_path(str(script))
    result_path = tmp_path / "result.json"
    request_path = tmp_path / "request.json"
    request_path.write_text(
        json.dumps({"output_path": str(result_path), "discard": discard}),
        encoding="utf-8",
    )
    return runtime["run"], request_path, result_path, hip_file, exit_calls


def test_houdini_stop_script_refuses_non_graphical_session_without_exit(
    tmp_path: Path, monkeypatch
) -> None:
    run, request_path, result_path, hip_file, exit_calls = _run(
        tmp_path, monkeypatch, dirty=True, ui_available=False
    )

    run(str(request_path))

    payload = json.loads(result_path.read_text(encoding="utf-8"))
    assert payload["ok"] is False
    assert payload["code"] == "session_dirty_state_unavailable"
    assert hip_file.save_calls == 0
    assert exit_calls == []


def test_houdini_stop_script_refuses_dirty_hip_without_save_or_exit(
    tmp_path: Path, monkeypatch
) -> None:
    run, request_path, result_path, hip_file, exit_calls = _run(tmp_path, monkeypatch, dirty=True)

    run(str(request_path))

    payload = json.loads(result_path.read_text(encoding="utf-8"))
    assert payload["ok"] is False
    assert payload["code"] == "session_unsaved_changes"
    assert hip_file.save_calls == 0
    assert exit_calls == []


@pytest.mark.parametrize("ui_available", [True, False])
def test_houdini_stop_script_discard_exits_without_dirty_check_or_save(
    tmp_path: Path, monkeypatch, ui_available: bool
) -> None:
    run, request_path, result_path, hip_file, exit_calls = _run(
        tmp_path,
        monkeypatch,
        dirty=True,
        ui_available=ui_available,
        discard=True,
    )

    with pytest.raises(_SystemExit):
        run(str(request_path))

    assert json.loads(result_path.read_text(encoding="utf-8")) == {
        "ok": True,
        "status": "stopping",
        "path": "C:/scene.hip",
    }
    assert hip_file.save_calls == 0
    assert exit_calls == [(0, True)]


def test_houdini_stop_script_publishes_marker_then_exits_without_save(
    tmp_path: Path, monkeypatch
) -> None:
    run, request_path, result_path, hip_file, exit_calls = _run(tmp_path, monkeypatch, dirty=False)

    with pytest.raises(_SystemExit):
        run(str(request_path))

    assert json.loads(result_path.read_text(encoding="utf-8")) == {
        "ok": True,
        "status": "stopping",
        "path": "C:/scene.hip",
    }
    assert hip_file.save_calls == 0
    assert exit_calls == [(0, True)]


def test_houdini_stop_script_preserves_marker_for_builtin_system_exit(
    tmp_path: Path, monkeypatch
) -> None:
    run, request_path, result_path, hip_file, exit_calls = _run(
        tmp_path,
        monkeypatch,
        dirty=False,
        exit_type=SystemExit,
    )

    with pytest.raises(SystemExit) as caught:
        run(str(request_path))

    assert caught.value.code == 0
    assert json.loads(result_path.read_text(encoding="utf-8")) == {
        "ok": True,
        "status": "stopping",
        "path": "C:/scene.hip",
    }
    assert hip_file.save_calls == 0
    assert exit_calls == [(0, True)]
