from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from houbridge.capture.viewport_info import ViewportInfoService
from houbridge.errors import BridgeError
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
        workspace = runner.parent
        (workspace / "result.json").write_text(
            json.dumps(self.payload, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )


def test_viewport_info_returns_only_stable_public_fields(tmp_path: Path) -> None:
    transport = _Transport(
        {
            "ok": True,
            "viewports": [
                {"name": "persp1", "type": "persp", "width": 960, "height": 540},
                {"name": "top1", "type": "top", "width": 960, "height": 540},
            ],
        }
    )
    service = ViewportInfoService(
        transport,
        workspaces=TemporaryWorkspaceService(temp_root=tmp_path),
    )

    assert service.info(_Session()) == {
        "viewports": [
            {"name": "persp1", "type": "persp", "width": 960, "height": 540},
            {"name": "top1", "type": "top", "width": 960, "height": 540},
        ]
    }
    assert not transport.runners[0].parent.exists()


def test_viewport_info_reports_missing_scene_viewer(tmp_path: Path) -> None:
    service = ViewportInfoService(
        _Transport({"ok": False, "message": "No Scene Viewer pane is available."}),
        workspaces=TemporaryWorkspaceService(temp_root=tmp_path),
    )

    with pytest.raises(BridgeError) as caught:
        service.info(_Session())

    assert caught.value.code == "viewport_unavailable"


def test_viewport_info_rejects_invalid_entry_shape(tmp_path: Path) -> None:
    service = ViewportInfoService(
        _Transport(
            {
                "ok": True,
                "viewports": [
                    {"name": "persp1", "type": "persp", "width": "960", "height": 540}
                ],
            }
        ),
        workspaces=TemporaryWorkspaceService(temp_root=tmp_path),
    )

    with pytest.raises(BridgeError) as caught:
        service.info(_Session())

    assert caught.value.code == "viewport_info_invalid"


def test_viewport_info_injected_source_lives_under_capture_script_boundary() -> None:
    from houbridge.houdini.scripts.capture import viewport_info

    source = Path(viewport_info.__file__).read_text(encoding="utf-8")
    assert "hou.ui.curDesktop().paneTabOfType(hou.paneTabType.SceneViewer)" in source
    assert "viewport.isVisible()" in source
    assert '"width": int(width)' in source
