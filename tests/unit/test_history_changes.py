from __future__ import annotations

from pathlib import Path

from houbridge.history import ParmChangedChange, materialize_action_changes
from houbridge.resource.store import ResourceStore
from houbridge.semantic_id import SemanticBase


class FixedSemanticGenerator:
    def generate(self, text: str, *, fallback_stem: str) -> SemanticBase:
        return SemanticBase(prefix="large-parm-value", tags=("large", "parm", "value"))


def _store(tmp_path: Path, monkeypatch) -> ResourceStore:
    import houbridge.resource.classifier as classifier

    monkeypatch.setattr(classifier.filetype, "guess", lambda _payload: None)
    return ResourceStore(
        tmp_path / "resources.db",
        semantic_generator=FixedSemanticGenerator(),
    )


def test_six_public_change_shapes_are_preserved(tmp_path: Path, monkeypatch) -> None:
    resources = _store(tmp_path, monkeypatch)
    raw = [
        {"type": "node_created", "node": 421, "before": None, "after": {"path": "/obj/geo1/noise1", "node_type": "attribnoise"}},
        {"type": "node_deleted", "node": 422, "before": {"path": "/obj/geo1/old", "node_type": "null"}, "after": None},
        {"type": "node_renamed", "node": 417, "before": "/obj/geo1/box1", "after": "/obj/geo1/box2"},
        {"type": "parm_changed", "node": 417, "path": "/obj/geo1/box2", "parm": "sizex", "before": "1", "after": "2"},
        {"type": "input_rewired", "node": 417, "path": "/obj/geo1/box2", "input": 0, "before": {"node": 416, "path": "/obj/geo1/grid1", "output": 0}, "after": None},
        {"type": "flag_changed", "node": 417, "path": "/obj/geo1/box2", "flag": "bypass", "before": False, "after": True},
    ]

    changes = materialize_action_changes(raw, resources=resources)

    assert [change.to_payload() for change in changes] == raw


def test_raw_parameter_value_at_4096_utf8_bytes_stays_inline(tmp_path: Path, monkeypatch) -> None:
    resources = _store(tmp_path, monkeypatch)
    value = "x" * 4096

    change = materialize_action_changes(
        [{"type": "parm_changed", "node": 1, "path": "/obj/a", "parm": "text", "before": value, "after": "small"}],
        resources=resources,
    )[0]

    assert isinstance(change, ParmChangedChange)
    assert change.before == value
    assert change.to_payload()["before"] == value


def test_oversized_raw_parameter_side_uses_normal_resource_classifier(tmp_path: Path, monkeypatch) -> None:
    resources = _store(tmp_path, monkeypatch)
    large = "多" * 1400  # 4200 UTF-8 bytes

    change = materialize_action_changes(
        [{"type": "parm_changed", "node": 7, "path": "/obj/a", "parm": "expr", "before": "$HIP/a.$F.bgeo", "after": large}],
        resources=resources,
    )[0]

    payload = change.to_payload()
    assert payload["before"] == "$HIP/a.$F.bgeo"
    omitted = payload["after"]
    assert isinstance(omitted, dict)
    assert set(omitted) == {"omitted", "resource", "tokens"}
    assert omitted["omitted"] is True
    assert resources.get_bytes(str(omitted["resource"])) == large.encode("utf-8")
    resource = resources.get(str(omitted["resource"]))
    assert resource is not None
    assert omitted["tokens"] == resource.token_count
    assert resource.mime == "text/plain"


def test_oversized_json_shaped_raw_parameter_uses_json_resource_classification(
    tmp_path: Path, monkeypatch
) -> None:
    resources = _store(tmp_path, monkeypatch)
    value = '{"expression":"' + ("x" * 4100) + '"}'

    change = materialize_action_changes(
        [{"type": "parm_changed", "node": 7, "path": "/obj/a", "parm": "expr", "before": "small", "after": value}],
        resources=resources,
    )[0]

    omitted = change.to_payload()["after"]
    assert isinstance(omitted, dict)
    resource_id = str(omitted["resource"])
    assert resources.get_bytes(resource_id) == value.encode("utf-8")
    resource = resources.get(resource_id)
    assert resource is not None
    assert resource.mime == "application/json"
