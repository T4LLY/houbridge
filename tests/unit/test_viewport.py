from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from houbridge.capture.viewport_info import ViewportInfoService
from houbridge.errors import BridgeError
from houbridge.houdini.scripts.capture import runtime as capture_runtime
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


def test_viewport_info_returns_scene_viewer_catalog(tmp_path: Path) -> None:
    transport = _Transport(
        {
            "ok": True,
            "panes": [
                {
                    "name": "panetab1",
                    "current_node": "/obj/robot/OUT",
                    "viewports": [
                        {
                            "name": "persp1",
                            "type": "persp",
                            "width": 960,
                            "height": 540,
                        },
                        {
                            "name": "top1",
                            "type": "top",
                            "width": 960,
                            "height": 540,
                        },
                    ],
                },
                {
                    "name": "panetab4",
                    "current_node": None,
                    "viewports": [],
                },
            ],
        }
    )
    service = ViewportInfoService(
        transport,
        workspaces=TemporaryWorkspaceService(temp_root=tmp_path),
    )

    assert service.info(_Session()) == {
        "panes": [
            {
                "name": "panetab1",
                "current_node": "/obj/robot/OUT",
                "viewports": [
                    {
                        "name": "persp1",
                        "type": "persp",
                        "width": 960,
                        "height": 540,
                    },
                    {
                        "name": "top1",
                        "type": "top",
                        "width": 960,
                        "height": 540,
                    },
                ],
            },
            {
                "name": "panetab4",
                "current_node": None,
                "viewports": [],
            },
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


def test_viewport_info_rejects_invalid_pane_shape(tmp_path: Path) -> None:
    service = ViewportInfoService(
        _Transport(
            {
                "ok": True,
                "panes": [
                    {
                        "name": "panetab1",
                        "current_node": 42,
                        "viewports": [],
                    }
                ],
            }
        ),
        workspaces=TemporaryWorkspaceService(temp_root=tmp_path),
    )

    with pytest.raises(BridgeError) as caught:
        service.info(_Session())

    assert caught.value.code == "viewport_info_invalid"


def test_scene_viewer_catalog_lists_all_visible_scene_viewer_tabs_and_viewports() -> None:
    viewport_types = SimpleNamespace(
        Top=object(),
        Bottom=object(),
        Front=object(),
        Back=object(),
        Left=object(),
        Right=object(),
        Perspective=object(),
        UV=object(),
    )

    class _Node:
        def __init__(self, path: str) -> None:
            self._path = path

        def path(self) -> str:
            return self._path

    class _Viewport:
        def __init__(
            self,
            name: str,
            kind,
            geometry: tuple[int, int, int, int],
            *,
            visible: bool = True,
        ) -> None:
            self._name = name
            self._kind = kind
            self._geometry = geometry
            self._visible = visible

        def name(self) -> str:
            return self._name

        def type(self):
            return self._kind

        def isVisible(self) -> bool:
            return self._visible

        def geometry(self) -> tuple[int, int, int, int]:
            return self._geometry

    class _PaneTab:
        def __init__(self, name: str, kind) -> None:
            self._name = name
            self._kind = kind

        def name(self) -> str:
            return self._name

        def type(self):
            return self._kind

    class _SceneViewer(_PaneTab):
        def __init__(self, name: str, node, viewports) -> None:
            super().__init__(name, "scene_viewer")
            self._node = node
            self._viewports = tuple(viewports)

        def currentNode(self):
            return self._node

        def viewports(self):
            return self._viewports

    scene_a = _SceneViewer(
        "panetab1",
        _Node("/obj/robot/OUT"),
        [
            _Viewport("persp1", viewport_types.Perspective, (0, 0, 1280, 720)),
            _Viewport("top1", viewport_types.Top, (0, 0, 640, 360)),
            _Viewport(
                "right1",
                viewport_types.Right,
                (-1, -1, -1, -1),
                visible=False,
            ),
        ],
    )
    scene_b = _SceneViewer("panetab4", None, [])
    other = _PaneTab("panetab2", "network_editor")
    hou = SimpleNamespace(
        ui=SimpleNamespace(paneTabs=lambda: (scene_a, other, scene_b)),
        paneTabType=SimpleNamespace(SceneViewer="scene_viewer"),
        geometryViewportType=viewport_types,
    )

    scenes = capture_runtime.list_scene_viewers(hou)

    assert scenes == (scene_a, scene_b)
    assert capture_runtime.describe_scene_viewers(scenes, hou) == {
        "panes": [
            {
                "name": "panetab1",
                "current_node": "/obj/robot/OUT",
                "viewports": [
                    {
                        "name": "persp1",
                        "type": "persp",
                        "width": 1280,
                        "height": 720,
                    },
                    {
                        "name": "top1",
                        "type": "top",
                        "width": 640,
                        "height": 360,
                    },
                ],
            },
            {
                "name": "panetab4",
                "current_node": None,
                "viewports": [],
            },
        ]
    }


def test_viewport_info_injected_source_reuses_capture_runtime_catalog() -> None:
    from houbridge.houdini.scripts.capture import viewport_info

    source = Path(viewport_info.__file__).read_text(encoding="utf-8")
    assert 'runtime["list_scene_viewers"](hou)' in source
    assert 'runtime["describe_scene_viewers"](scenes, hou)' in source


def test_scene_viewer_resolution_requires_unambiguous_visible_pane() -> None:
    viewport_types = SimpleNamespace(
        Top=object(),
        Bottom=object(),
        Front=object(),
        Back=object(),
        Left=object(),
        Right=object(),
        Perspective=object(),
        UV=object(),
    )

    class _SceneViewer:
        def __init__(self, name: str, node_path: str | None) -> None:
            self._name = name
            self._node_path = node_path

        def name(self) -> str:
            return self._name

        def type(self):
            return "scene_viewer"

        def currentNode(self):
            if self._node_path is None:
                return None
            return SimpleNamespace(path=lambda: self._node_path)

        def viewports(self):
            return ()

    scene_a = _SceneViewer("panetab1", "/obj/a/OUT")
    scene_b = _SceneViewer("panetab4", "/obj/b/OUT")
    scenes = [scene_a, scene_b]
    hou = SimpleNamespace(
        ui=SimpleNamespace(paneTabs=lambda: tuple(scenes)),
        paneTabType=SimpleNamespace(SceneViewer="scene_viewer"),
        geometryViewportType=viewport_types,
    )

    with pytest.raises(capture_runtime.CaptureRequestError) as ambiguous:
        capture_runtime.resolve_scene_viewer(hou)
    assert ambiguous.value.code == "scene_viewer_ambiguous"
    assert [pane["name"] for pane in ambiguous.value.context["panes"]] == [
        "panetab1",
        "panetab4",
    ]

    assert capture_runtime.resolve_scene_viewer(hou, "panetab4") is scene_b

    scenes[:] = [scene_a]
    assert capture_runtime.resolve_scene_viewer(hou) is scene_a
    scenes[:] = [scene_a, scene_b]

    with pytest.raises(capture_runtime.CaptureRequestError) as missing:
        capture_runtime.resolve_scene_viewer(hou, "missing")
    assert missing.value.code == "scene_viewer_not_found"
    assert [pane["name"] for pane in missing.value.context["panes"]] == [
        "panetab1",
        "panetab4",
    ]

    scenes[:] = [scene_a, _SceneViewer("panetab1", "/obj/c/OUT")]
    with pytest.raises(capture_runtime.CaptureRequestError) as duplicate:
        capture_runtime.resolve_scene_viewer(hou, "panetab1")
    assert duplicate.value.code == "scene_viewer_ambiguous"

    scenes.clear()
    with pytest.raises(capture_runtime.CaptureRequestError) as unavailable:
        capture_runtime.resolve_scene_viewer(hou)
    assert unavailable.value.code == "viewport_unavailable"
