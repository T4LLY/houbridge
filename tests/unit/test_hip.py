from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from houbridge.errors import BridgeError
from houbridge.hip import HipFileService
from houbridge.houdini.scripts.hip import operation
from houbridge.houdini.transport import HoudiniTarget
from houbridge.temporary_workspace import TemporaryWorkspaceService


class _Session(SimpleNamespace):
    target = HoudiniTarget("127.0.0.1", 49152)


class _Transport:
    def __init__(self, payload: object) -> None:
        self.payload = payload
        self.runners: list[Path] = []

    def execute_script(self, _target, runner: Path):
        self.runners.append(runner)
        (runner.parent / "result.json").write_text(
            json.dumps(self.payload, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )


def test_hip_info_returns_exact_state_and_cleans_workspace(tmp_path: Path) -> None:
    transport = _Transport(
        {"ok": True, "path": "C:/project/scene.hip", "dirty": True, "new": False}
    )
    service = HipFileService(
        transport,
        workspaces=TemporaryWorkspaceService(temp_root=tmp_path),
    )

    assert service.info(_Session()) == {
        "path": "C:/project/scene.hip",
        "dirty": True,
        "new": False,
    }
    assert not transport.runners[0].parent.exists()


def test_hip_save_returns_path_and_status(tmp_path: Path) -> None:
    service = HipFileService(
        _Transport(
            {"ok": True, "path": "C:/project/scene.hip", "status": "saved"}
        ),
        workspaces=TemporaryWorkspaceService(temp_root=tmp_path),
    )

    assert service.save(_Session()) == {
        "path": "C:/project/scene.hip",
        "status": "saved",
    }


def test_hip_save_rejects_invalid_status(tmp_path: Path) -> None:
    service = HipFileService(
        _Transport(
            {"ok": True, "path": "C:/project/scene.hip", "status": "unknown"}
        ),
        workspaces=TemporaryWorkspaceService(temp_root=tmp_path),
    )

    with pytest.raises(BridgeError) as caught:
        service.save(_Session())

    assert caught.value.code == "hip_operation_failed"


def test_hip_save_propagates_missing_target_error(tmp_path: Path) -> None:
    service = HipFileService(
        _Transport(
            {
                "ok": False,
                "code": "hip_save_target_missing",
                "message": "Current HIP file has no established save target.",
            }
        ),
        workspaces=TemporaryWorkspaceService(temp_root=tmp_path),
    )

    with pytest.raises(BridgeError) as caught:
        service.save(_Session())

    assert caught.value.code == "hip_save_target_missing"


def test_houdini_hip_save_calls_native_save_when_dirty(monkeypatch, tmp_path: Path) -> None:
    class _HipFile:
        def __init__(self) -> None:
            self.saved = False

        def path(self) -> str:
            return "C:/project/scene.hip"

        def hasUnsavedChanges(self) -> bool:
            return not self.saved

        def isNewFile(self) -> bool:
            return False

        def save(self) -> None:
            self.saved = True

    hip_file = _HipFile()
    monkeypatch.setitem(sys.modules, "hou", SimpleNamespace(hipFile=hip_file))
    result_path = tmp_path / "result.json"
    request_path = tmp_path / "request.json"
    request_path.write_text(
        json.dumps({"mode": "save", "output_path": str(result_path)}),
        encoding="utf-8",
    )

    operation.run(str(request_path))

    assert hip_file.saved is True
    assert json.loads(result_path.read_text(encoding="utf-8")) == {
        "ok": True,
        "path": "C:/project/scene.hip",
        "status": "saved",
    }


def test_houdini_hip_save_skips_native_save_when_clean(
    monkeypatch, tmp_path: Path
) -> None:
    class _HipFile:
        def __init__(self) -> None:
            self.save_calls = 0

        def path(self) -> str:
            return "C:/project/scene.hip"

        def hasUnsavedChanges(self) -> bool:
            return False

        def isNewFile(self) -> bool:
            return False

        def save(self) -> None:
            self.save_calls += 1

    hip_file = _HipFile()
    monkeypatch.setitem(sys.modules, "hou", SimpleNamespace(hipFile=hip_file))
    result_path = tmp_path / "result.json"
    request_path = tmp_path / "request.json"
    request_path.write_text(
        json.dumps({"mode": "save", "output_path": str(result_path)}),
        encoding="utf-8",
    )

    operation.run(str(request_path))

    assert hip_file.save_calls == 0
    assert json.loads(result_path.read_text(encoding="utf-8")) == {
        "ok": True,
        "path": "C:/project/scene.hip",
        "status": "unchanged",
    }


def test_houdini_hip_save_refuses_new_file_without_calling_save(
    monkeypatch, tmp_path: Path
) -> None:
    class _HipFile:
        def __init__(self) -> None:
            self.save_calls = 0

        def isNewFile(self) -> bool:
            return True

        def save(self) -> None:
            self.save_calls += 1

    hip_file = _HipFile()
    monkeypatch.setitem(sys.modules, "hou", SimpleNamespace(hipFile=hip_file))
    result_path = tmp_path / "result.json"
    request_path = tmp_path / "request.json"
    request_path.write_text(
        json.dumps({"mode": "save", "output_path": str(result_path)}),
        encoding="utf-8",
    )

    operation.run(str(request_path))

    assert hip_file.save_calls == 0
    assert json.loads(result_path.read_text(encoding="utf-8")) == {
        "ok": False,
        "code": "hip_save_target_missing",
        "message": "Current HIP file has no established save target.",
    }
