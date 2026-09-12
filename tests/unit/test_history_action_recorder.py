from __future__ import annotations

import runpy
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest


SCRIPT = (
    Path(__file__).parents[2]
    / "src"
    / "houbridge"
    / "houdini"
    / "scripts"
    / "history"
    / "action_recorder.py"
)


class FakeParm:
    def __init__(self, name: str, value: str) -> None:
        self._name = name
        self.value = value

    def name(self) -> str:
        return self._name

    def rawValue(self) -> str:
        return self.value


class FakeType:
    def __init__(self, name: str) -> None:
        self._name = name

    def name(self) -> str:
        return self._name


class FakeConnection:
    def __init__(self, source: "FakeNode", input_index: int, output_index: int = 0) -> None:
        self.source = source
        self.input_index = input_index
        self.output_index = output_index

    def inputNode(self):
        return self.source

    def inputIndex(self) -> int:
        return self.input_index

    def outputIndex(self) -> int:
        return self.output_index


class FakeNode:
    def __init__(
        self,
        hou_module,
        session_id: int,
        path: str,
        node_type: str = "null",
        *,
        parent: "FakeNode | None" = None,
        parms: dict[str, str] | None = None,
    ) -> None:
        self.hou = hou_module
        self._session_id = session_id
        self._path = path
        self._type = FakeType(node_type)
        self.parent = parent
        self.children: list[FakeNode] = []
        self._parms = {name: FakeParm(name, value) for name, value in (parms or {}).items()}
        self._inputs: dict[int, FakeConnection] = {}
        self.flags = {
            "bypass": False,
            "display": False,
            "render": False,
            "template": False,
            "selectable_template": False,
        }
        self.callbacks: list[tuple[tuple[object, ...], object]] = []
        if parent is not None:
            parent.children.append(self)
        hou_module._nodes[session_id] = self

    def sessionId(self) -> int:
        return self._session_id

    def path(self) -> str:
        return self._path

    def type(self) -> FakeType:
        return self._type

    def parms(self):
        return tuple(self._parms.values())

    def inputConnections(self):
        return tuple(self._inputs[index] for index in sorted(self._inputs))

    def allSubChildren(self):
        result: list[FakeNode] = []
        for child in self.children:
            result.append(child)
            result.extend(child.allSubChildren())
        return tuple(result)

    def addEventCallback(self, event_types, callback) -> None:
        self.callbacks.append((tuple(event_types), callback))

    def removeEventCallback(self, event_types, callback) -> None:
        target = (tuple(event_types), callback)
        if target not in self.callbacks:
            raise RuntimeError("callback missing")
        self.callbacks.remove(target)

    def emit(self, event_type, **kwargs) -> None:
        for event_types, callback in tuple(self.callbacks):
            if event_type in event_types:
                callback(node=self, event_type=event_type, **kwargs)

    def rename(self, path: str) -> None:
        self._path = path
        self.emit(self.hou.nodeEventType.NameChanged)

    def set_parm(self, name: str, value: str, *, whole_node_event: bool = False) -> None:
        self._parms[name].value = value
        self.emit(
            self.hou.nodeEventType.ParmTupleChanged,
            parm_tuple=None if whole_node_event else object(),
        )

    def set_input(self, index: int, source: "FakeNode | None", output: int = 0) -> None:
        if source is None:
            self._inputs.pop(index, None)
        else:
            self._inputs[index] = FakeConnection(source, index, output)
        self.emit(self.hou.nodeEventType.InputRewired, input_index=index)

    def set_flag(self, name: str, value: bool) -> None:
        self.flags[name] = value
        self.emit(self.hou.nodeEventType.FlagChanged)

    def create_child(self, session_id: int, name: str, *, parms: dict[str, str] | None = None):
        child = FakeNode(
            self.hou,
            session_id,
            f"{self._path.rstrip('/')}/{name}",
            parent=self,
            parms=parms,
        )
        self.emit(self.hou.nodeEventType.ChildCreated, child_node=child)
        return child

    def destroy(self) -> None:
        self.emit(self.hou.nodeEventType.BeingDeleted)
        if self.parent is not None:
            self.parent.emit(self.hou.nodeEventType.ChildDeleted, child_node=self)
            self.parent.children.remove(self)
        self.hou._nodes.pop(self._session_id, None)

    def isBypassed(self) -> bool:
        return self.flags["bypass"]

    def isDisplayFlagSet(self) -> bool:
        return self.flags["display"]

    def isRenderFlagSet(self) -> bool:
        return self.flags["render"]

    def isTemplateFlagSet(self) -> bool:
        return self.flags["template"]

    def isSelectableTemplateFlagSet(self) -> bool:
        return self.flags["selectable_template"]


@pytest.fixture
def fake_hou(monkeypatch: pytest.MonkeyPatch):
    hou = types.ModuleType("hou")
    hou.nodeEventType = SimpleNamespace(
        ChildCreated=object(),
        ChildDeleted=object(),
        BeingDeleted=object(),
        NameChanged=object(),
        ParmTupleChanged=object(),
        InputRewired=object(),
        FlagChanged=object(),
    )
    hou._nodes = {}
    root = FakeNode(hou, 1, "/", "root")
    obj = FakeNode(hou, 2, "/obj", "manager", parent=root)
    hou.node = lambda path: root if path == "/" else None
    hou.nodeBySessionId = lambda session_id: hou._nodes.get(session_id)
    monkeypatch.setitem(sys.modules, "hou", hou)
    return hou, root, obj


def _recorder_class():
    return runpy.run_path(str(SCRIPT))["ActionRecorder"]


def _by_type(changes, change_type: str):
    return [change for change in changes if change["type"] == change_type]


def test_existing_node_compacts_rename_parm_rewire_and_flag_to_net_changes(fake_hou) -> None:
    hou, _root, obj = fake_hou
    upstream = FakeNode(hou, 10, "/obj/grid1", "grid", parent=obj)
    node = FakeNode(hou, 11, "/obj/box1", "box", parent=obj, parms={"sizex": "1"})
    node._inputs[0] = FakeConnection(upstream, 0, 0)
    recorder = _recorder_class()()

    node.rename("/obj/box2")
    node.set_parm("sizex", "2", whole_node_event=True)
    node.set_input(0, None)
    node.set_flag("bypass", True)
    changes = recorder.finalize()

    assert changes is not None
    assert _by_type(changes, "node_renamed") == [
        {"type": "node_renamed", "node": 11, "before": "/obj/box1", "after": "/obj/box2"}
    ]
    assert _by_type(changes, "parm_changed") == [
        {"type": "parm_changed", "node": 11, "path": "/obj/box2", "parm": "sizex", "before": "1", "after": "2"}
    ]
    assert _by_type(changes, "input_rewired") == [
        {"type": "input_rewired", "node": 11, "path": "/obj/box2", "input": 0, "before": {"node": 10, "path": "/obj/grid1", "output": 0}, "after": None}
    ]
    assert _by_type(changes, "flag_changed") == [
        {"type": "flag_changed", "node": 11, "path": "/obj/box2", "flag": "bypass", "before": False, "after": True}
    ]


def test_parameter_change_returning_to_original_is_dropped(fake_hou) -> None:
    hou, _root, obj = fake_hou
    node = FakeNode(hou, 11, "/obj/box1", "box", parent=obj, parms={"sizex": "1"})
    recorder = _recorder_class()()

    node.set_parm("sizex", "2")
    node.set_parm("sizex", "1")

    assert recorder.finalize() == []


def test_created_node_uses_final_path_without_separate_rename_and_keeps_later_delta(fake_hou) -> None:
    _hou, _root, obj = fake_hou
    recorder = _recorder_class()()

    node = obj.create_child(20, "null1", parms={"label": "a"})
    node.rename("/obj/final1")
    node.set_parm("label", "b")
    changes = recorder.finalize()

    assert changes is not None
    assert _by_type(changes, "node_created") == [
        {"type": "node_created", "node": 20, "before": None, "after": {"path": "/obj/final1", "node_type": "null"}}
    ]
    assert _by_type(changes, "node_renamed") == []
    assert _by_type(changes, "parm_changed") == [
        {"type": "parm_changed", "node": 20, "path": "/obj/final1", "parm": "label", "before": "a", "after": "b"}
    ]


def test_created_then_deleted_node_has_no_final_change(fake_hou) -> None:
    _hou, _root, obj = fake_hou
    recorder = _recorder_class()()

    node = obj.create_child(20, "null1")
    node.destroy()

    assert recorder.finalize() == []


def test_existing_deleted_node_drops_intermediate_edits(fake_hou) -> None:
    hou, _root, obj = fake_hou
    node = FakeNode(hou, 11, "/obj/box1", "box", parent=obj, parms={"sizex": "1"})
    recorder = _recorder_class()()

    node.rename("/obj/box2")
    node.set_parm("sizex", "2")
    node.destroy()
    changes = recorder.finalize()

    assert changes == [
        {"type": "node_deleted", "node": 11, "before": {"path": "/obj/box1", "node_type": "box"}, "after": None}
    ]


def test_upstream_rename_does_not_look_like_input_rewire(fake_hou) -> None:
    hou, _root, obj = fake_hou
    upstream = FakeNode(hou, 10, "/obj/grid1", "grid", parent=obj)
    node = FakeNode(hou, 11, "/obj/box1", "box", parent=obj)
    node._inputs[0] = FakeConnection(upstream, 0, 0)
    recorder = _recorder_class()()

    upstream.rename("/obj/grid2")
    node.emit(hou.nodeEventType.InputRewired, input_index=0)
    changes = recorder.finalize()

    assert _by_type(changes, "input_rewired") == []


def test_scene_replacement_discards_pending_baseline_and_changes(fake_hou) -> None:
    hou, _root, obj = fake_hou
    node = FakeNode(hou, 11, "/obj/box1", "box", parent=obj, parms={"sizex": "1"})
    generation = [4]
    recorder = _recorder_class()(scene_generation_getter=lambda: generation[0])

    node.set_parm("sizex", "2")
    generation[0] = 5

    assert recorder.finalize() is None
    assert node.callbacks == []


def test_ancestor_rename_does_not_emit_child_rename_when_child_later_changes(fake_hou) -> None:
    hou, _root, obj = fake_hou
    parent = FakeNode(hou, 10, "/obj/geo1", "geo", parent=obj)
    child = FakeNode(hou, 11, "/obj/geo1/box1", "box", parent=parent, parms={"sizex": "1"})
    recorder = _recorder_class()()

    parent.rename("/obj/geo2")
    child._path = "/obj/geo2/box1"
    child.set_parm("sizex", "2")
    changes = recorder.finalize()

    assert _by_type(changes, "node_renamed") == [
        {"type": "node_renamed", "node": 10, "before": "/obj/geo1", "after": "/obj/geo2"}
    ]
    assert _by_type(changes, "parm_changed") == [
        {"type": "parm_changed", "node": 11, "path": "/obj/geo2/box1", "parm": "sizex", "before": "1", "after": "2"}
    ]
