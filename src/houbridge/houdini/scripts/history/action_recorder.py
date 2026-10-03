from __future__ import annotations

from typing import Callable


_FLAG_GETTERS = (
    ("bypass", "isBypassed"),
    ("display", "isDisplayFlagSet"),
    ("render", "isRenderFlagSet"),
    ("template", "isTemplateFlagSet"),
    ("selectable_template", "isSelectableTemplateFlagSet"),
)


class ActionRecorder:
    """Invocation-local Houdini Action baseline and six-change net compactor."""

    def __init__(self, *, scene_generation_getter: Callable[[], int] | None = None) -> None:
        import hou

        self._hou = hou
        self._scene_generation_getter = scene_generation_getter
        self._scene_generation = (
            None if scene_generation_getter is None else int(scene_generation_getter())
        )
        self._baseline: dict[int, dict[str, object]] = {}
        self._created: dict[int, dict[str, object]] = {}
        self._dirty: set[int] = set()
        self._renamed: set[int] = set()
        self._attached: dict[int, object] = {}
        self._closed = False
        self._callback = self._on_event
        self._events = self._tracked_events()

        root = hou.node("/")
        if root is None:
            raise RuntimeError("Houdini root node is unavailable.")
        try:
            for node in (root, *root.allSubChildren()):
                self._attach_existing(node)
        except BaseException:
            self.close()
            raise

    def finalize(self) -> list[dict[str, object]] | None:
        """Return net changes, or None when scene replacement invalidated the action."""

        try:
            if self._scene_was_replaced():
                self._discard()
                return None

            changes: list[dict[str, object]] = []
            for session_id in sorted(self._dirty & self._baseline.keys()):
                before = self._baseline[session_id]
                node = self._hou.nodeBySessionId(session_id)
                if node is None:
                    changes.append(_node_deleted(before))
                    continue
                after = _snapshot_node(node)
                changes.extend(
                    _diff_existing(before, after, renamed=session_id in self._renamed)
                )

            for session_id in sorted(self._created):
                node = self._hou.nodeBySessionId(session_id)
                if node is None:
                    continue
                initial = self._created[session_id]
                final = _snapshot_node(node)
                changes.append(_node_created(final))
                changes.extend(_diff_created(initial, final))

            self._discard()
            return changes
        finally:
            self.close()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for node in tuple(self._attached.values()):
            try:
                node.removeEventCallback(self._events, self._callback)
            except Exception:
                # Deleted nodes no longer have a callback to remove. Never use
                # removeAllEventCallbacks: it could remove callbacks owned by Houdini.
                pass
        self._attached.clear()

    def _attach_existing(self, node) -> None:
        session_id = int(node.sessionId())
        if session_id in self._attached:
            return
        self._baseline[session_id] = _snapshot_node(node)
        self._attach(node)

    def _attach_created(self, node) -> None:
        for candidate in (node, *node.allSubChildren()):
            session_id = int(candidate.sessionId())
            if session_id in self._baseline or session_id in self._created:
                continue
            self._created[session_id] = _snapshot_node(candidate)
            self._attach(candidate)

    def _attach(self, node) -> None:
        session_id = int(node.sessionId())
        self._attached[session_id] = node
        node.addEventCallback(self._events, self._callback)

    def _on_event(self, node, event_type, **kwargs) -> None:
        event = self._hou.nodeEventType
        if event_type == event.ChildCreated:
            child = kwargs.get("child_node")
            if child is not None:
                self._attach_created(child)
            return
        if event_type == event.ChildDeleted:
            child = kwargs.get("child_node")
            if child is not None:
                self._dirty.add(int(child.sessionId()))
            return

        session_id = int(node.sessionId())
        if event_type == event.NameChanged:
            self._renamed.add(session_id)
        if event_type in (
            event.BeingDeleted,
            event.NameChanged,
            event.ParmTupleChanged,
            event.InputRewired,
            event.FlagChanged,
        ):
            self._dirty.add(session_id)

    def _tracked_events(self) -> tuple[object, ...]:
        event = self._hou.nodeEventType
        return (
            event.ChildCreated,
            event.ChildDeleted,
            event.BeingDeleted,
            event.NameChanged,
            event.ParmTupleChanged,
            event.InputRewired,
            event.FlagChanged,
        )

    def _scene_was_replaced(self) -> bool:
        if self._scene_generation_getter is None:
            return False
        return int(self._scene_generation_getter()) != self._scene_generation

    def _discard(self) -> None:
        self._baseline.clear()
        self._created.clear()
        self._dirty.clear()
        self._renamed.clear()


def _snapshot_node(node) -> dict[str, object]:
    return {
        "session_id": int(node.sessionId()),
        "path": str(node.path()),
        "node_type": str(node.type().name()),
        "parms": {str(parm.name()): str(parm.rawValue()) for parm in node.parms()},
        "inputs": _snapshot_inputs(node),
        "flags": _snapshot_flags(node),
    }


def _snapshot_inputs(node) -> dict[int, dict[str, object]]:
    inputs: dict[int, dict[str, object]] = {}
    for connection in node.inputConnections():
        source = connection.inputNode()
        if source is None:
            continue
        inputs[int(connection.inputIndex())] = {
            "node": int(source.sessionId()),
            "path": str(source.path()),
            "output": int(connection.outputIndex()),
        }
    return inputs


def _snapshot_flags(node) -> dict[str, bool]:
    flags: dict[str, bool] = {}
    for name, getter_name in _FLAG_GETTERS:
        getter = getattr(node, getter_name, None)
        if getter is None:
            continue
        try:
            flags[name] = bool(getter())
        except Exception:
            # A method may exist on the Python class while the flag itself is
            # unavailable for this operator category.
            continue
    return flags


def _diff_existing(
    before: dict[str, object],
    after: dict[str, object],
    *,
    renamed: bool,
) -> list[dict[str, object]]:
    changes: list[dict[str, object]] = []
    node = int(after["session_id"])
    final_path = str(after["path"])

    if renamed and before["path"] != after["path"]:
        changes.append(
            {
                "type": "node_renamed",
                "node": node,
                "before": str(before["path"]),
                "after": final_path,
            }
        )
    changes.extend(_parm_changes(before, after, final_path=final_path))
    changes.extend(_input_changes(before, after, final_path=final_path))
    changes.extend(_flag_changes(before, after, final_path=final_path))
    return changes


def _diff_created(
    before: dict[str, object],
    after: dict[str, object],
) -> list[dict[str, object]]:
    final_path = str(after["path"])
    return [
        *_parm_changes(before, after, final_path=final_path),
        *_input_changes(before, after, final_path=final_path),
        *_flag_changes(before, after, final_path=final_path),
    ]


def _parm_changes(
    before: dict[str, object],
    after: dict[str, object],
    *,
    final_path: str,
) -> list[dict[str, object]]:
    old = before["parms"]
    new = after["parms"]
    assert isinstance(old, dict) and isinstance(new, dict)
    changes: list[dict[str, object]] = []
    for name in sorted(old.keys() | new.keys()):
        old_value = old.get(name)
        new_value = new.get(name)
        if old_value == new_value:
            continue
        changes.append(
            {
                "type": "parm_changed",
                "node": int(after["session_id"]),
                "path": final_path,
                "parm": str(name),
                "before": old_value,
                "after": new_value,
            }
        )
    return changes


def _input_changes(
    before: dict[str, object],
    after: dict[str, object],
    *,
    final_path: str,
) -> list[dict[str, object]]:
    old = before["inputs"]
    new = after["inputs"]
    assert isinstance(old, dict) and isinstance(new, dict)
    changes: list[dict[str, object]] = []
    for input_index in sorted(old.keys() | new.keys()):
        old_connection = old.get(input_index)
        new_connection = new.get(input_index)
        if _connection_identity(old_connection) == _connection_identity(new_connection):
            continue
        changes.append(
            {
                "type": "input_rewired",
                "node": int(after["session_id"]),
                "path": final_path,
                "input": int(input_index),
                "before": old_connection,
                "after": new_connection,
            }
        )
    return changes


def _flag_changes(
    before: dict[str, object],
    after: dict[str, object],
    *,
    final_path: str,
) -> list[dict[str, object]]:
    old = before["flags"]
    new = after["flags"]
    assert isinstance(old, dict) and isinstance(new, dict)
    changes: list[dict[str, object]] = []
    for flag in sorted(old.keys() & new.keys()):
        if old[flag] == new[flag]:
            continue
        changes.append(
            {
                "type": "flag_changed",
                "node": int(after["session_id"]),
                "path": final_path,
                "flag": str(flag),
                "before": bool(old[flag]),
                "after": bool(new[flag]),
            }
        )
    return changes


def _connection_identity(value: object) -> tuple[int, int] | None:
    if value is None:
        return None
    assert isinstance(value, dict)
    return int(value["node"]), int(value["output"])


def _node_created(snapshot: dict[str, object]) -> dict[str, object]:
    return {
        "type": "node_created",
        "node": int(snapshot["session_id"]),
        "before": None,
        "after": {
            "path": str(snapshot["path"]),
            "node_type": str(snapshot["node_type"]),
        },
    }


def _node_deleted(snapshot: dict[str, object]) -> dict[str, object]:
    return {
        "type": "node_deleted",
        "node": int(snapshot["session_id"]),
        "before": {
            "path": str(snapshot["path"]),
            "node_type": str(snapshot["node_type"]),
        },
        "after": None,
    }
