from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Mapping, TypeAlias

from houbridge.errors import BridgeError
from houbridge.resource.store import ResourceStore


_INLINE_RAW_VALUE_BYTES = 4096
_SUPPORTED_FLAGS = {
    "bypass",
    "display",
    "render",
    "template",
    "selectable_template",
}


@dataclass(frozen=True, slots=True)
class OmittedRawValue:
    resource: str
    tokens: int
    omitted: Literal[True] = True

    def to_payload(self) -> dict[str, object]:
        return {
            "omitted": True,
            "resource": self.resource,
            "tokens": self.tokens,
        }


HistoryRawValue: TypeAlias = str | OmittedRawValue


@dataclass(frozen=True, slots=True)
class NodeState:
    path: str
    node_type: str

    def to_payload(self) -> dict[str, str]:
        return {"path": self.path, "node_type": self.node_type}


@dataclass(frozen=True, slots=True)
class ConnectionState:
    node: int
    path: str
    output: int

    def to_payload(self) -> dict[str, object]:
        return {"node": self.node, "path": self.path, "output": self.output}


@dataclass(frozen=True, slots=True)
class NodeCreatedChange:
    node: int
    after: NodeState
    type: Literal["node_created"] = "node_created"

    def to_payload(self) -> dict[str, object]:
        return {
            "type": self.type,
            "node": self.node,
            "before": None,
            "after": self.after.to_payload(),
        }


@dataclass(frozen=True, slots=True)
class NodeDeletedChange:
    node: int
    before: NodeState
    type: Literal["node_deleted"] = "node_deleted"

    def to_payload(self) -> dict[str, object]:
        return {
            "type": self.type,
            "node": self.node,
            "before": self.before.to_payload(),
            "after": None,
        }


@dataclass(frozen=True, slots=True)
class NodeRenamedChange:
    node: int
    before: str
    after: str
    type: Literal["node_renamed"] = "node_renamed"

    def to_payload(self) -> dict[str, object]:
        return {
            "type": self.type,
            "node": self.node,
            "before": self.before,
            "after": self.after,
        }


@dataclass(frozen=True, slots=True)
class ParmChangedChange:
    node: int
    path: str
    parm: str
    before: HistoryRawValue
    after: HistoryRawValue
    type: Literal["parm_changed"] = "parm_changed"

    def to_payload(self) -> dict[str, object]:
        return {
            "type": self.type,
            "node": self.node,
            "path": self.path,
            "parm": self.parm,
            "before": _raw_value_payload(self.before),
            "after": _raw_value_payload(self.after),
        }


@dataclass(frozen=True, slots=True)
class InputRewiredChange:
    node: int
    path: str
    input: int
    before: ConnectionState | None
    after: ConnectionState | None
    type: Literal["input_rewired"] = "input_rewired"

    def to_payload(self) -> dict[str, object]:
        return {
            "type": self.type,
            "node": self.node,
            "path": self.path,
            "input": self.input,
            "before": None if self.before is None else self.before.to_payload(),
            "after": None if self.after is None else self.after.to_payload(),
        }


@dataclass(frozen=True, slots=True)
class FlagChangedChange:
    node: int
    path: str
    flag: Literal[
        "bypass",
        "display",
        "render",
        "template",
        "selectable_template",
    ]
    before: bool
    after: bool
    type: Literal["flag_changed"] = "flag_changed"

    def to_payload(self) -> dict[str, object]:
        return {
            "type": self.type,
            "node": self.node,
            "path": self.path,
            "flag": self.flag,
            "before": self.before,
            "after": self.after,
        }


ActionChange: TypeAlias = (
    NodeCreatedChange
    | NodeDeletedChange
    | NodeRenamedChange
    | ParmChangedChange
    | InputRewiredChange
    | FlagChangedChange
)


def materialize_action_changes(
    raw_changes: list[object] | tuple[object, ...],
    *,
    resources: ResourceStore,
) -> tuple[ActionChange, ...]:
    """Validate recorder output and bound raw parameter bodies through Resource."""

    return tuple(_materialize_change(value, resources=resources) for value in raw_changes)


def _materialize_change(value: object, *, resources: ResourceStore) -> ActionChange:
    data = _mapping(value)
    change_type = data.get("type")
    if change_type == "node_created":
        _exact_keys(data, {"type", "node", "before", "after"})
        if data["before"] is not None:
            raise _invalid()
        return NodeCreatedChange(
            node=_node_id(data["node"]),
            after=_node_state(data["after"]),
        )
    if change_type == "node_deleted":
        _exact_keys(data, {"type", "node", "before", "after"})
        if data["after"] is not None:
            raise _invalid()
        return NodeDeletedChange(
            node=_node_id(data["node"]),
            before=_node_state(data["before"]),
        )
    if change_type == "node_renamed":
        _exact_keys(data, {"type", "node", "before", "after"})
        return NodeRenamedChange(
            node=_node_id(data["node"]),
            before=_string(data["before"]),
            after=_string(data["after"]),
        )
    if change_type == "parm_changed":
        _exact_keys(data, {"type", "node", "path", "parm", "before", "after"})
        return ParmChangedChange(
            node=_node_id(data["node"]),
            path=_string(data["path"]),
            parm=_string(data["parm"]),
            before=_bounded_raw_value(_string(data["before"]), resources=resources),
            after=_bounded_raw_value(_string(data["after"]), resources=resources),
        )
    if change_type == "input_rewired":
        _exact_keys(data, {"type", "node", "path", "input", "before", "after"})
        return InputRewiredChange(
            node=_node_id(data["node"]),
            path=_string(data["path"]),
            input=_non_negative_int(data["input"]),
            before=_connection_state(data["before"]),
            after=_connection_state(data["after"]),
        )
    if change_type == "flag_changed":
        _exact_keys(data, {"type", "node", "path", "flag", "before", "after"})
        flag = _string(data["flag"])
        if flag not in _SUPPORTED_FLAGS:
            raise _invalid()
        before = data["before"]
        after = data["after"]
        if not isinstance(before, bool) or not isinstance(after, bool):
            raise _invalid()
        return FlagChangedChange(
            node=_node_id(data["node"]),
            path=_string(data["path"]),
            flag=flag,  # type: ignore[arg-type]
            before=before,
            after=after,
        )
    raise _invalid()


def _bounded_raw_value(value: str, *, resources: ResourceStore) -> HistoryRawValue:
    payload = value.encode("utf-8")
    if len(payload) <= _INLINE_RAW_VALUE_BYTES:
        return value
    resource = resources.put_bytes(payload)
    if resource.token_count is None:
        raise BridgeError(
            "history_resource_invalid",
            "Oversized History parameter Resource is missing token metadata.",
        )
    return OmittedRawValue(
        resource=resource.semantic_alias,
        tokens=resource.token_count,
    )


def _raw_value_payload(value: HistoryRawValue) -> object:
    return value if isinstance(value, str) else value.to_payload()


def _node_state(value: object) -> NodeState:
    data = _mapping(value)
    _exact_keys(data, {"path", "node_type"})
    return NodeState(path=_string(data["path"]), node_type=_string(data["node_type"]))


def _connection_state(value: object) -> ConnectionState | None:
    if value is None:
        return None
    data = _mapping(value)
    _exact_keys(data, {"node", "path", "output"})
    return ConnectionState(
        node=_node_id(data["node"]),
        path=_string(data["path"]),
        output=_non_negative_int(data["output"]),
    )


def _mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise _invalid()
    return value


def _exact_keys(value: Mapping[str, object], expected: set[str]) -> None:
    if set(value) != expected:
        raise _invalid()


def _string(value: object) -> str:
    if not isinstance(value, str):
        raise _invalid()
    return value


def _node_id(value: object) -> int:
    return _non_negative_int(value)


def _non_negative_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise _invalid()
    return value


def _invalid() -> BridgeError:
    return BridgeError(
        "history_change_invalid",
        "Houdini Action recorder returned an invalid History change.",
    )
