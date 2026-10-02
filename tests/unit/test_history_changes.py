from __future__ import annotations

from pathlib import Path

import pytest

from houbridge.errors import BridgeError
from houbridge.history import ParmChangedChange, materialize_action_changes
from houbridge.resource.store import ResourceStore
from houbridge.semantic_id import SemanticBase


class FixedSemanticGenerator:
    def generate(self, text: str, *, fallback_stem: str) -> SemanticBase:
        return SemanticBase(prefix="large-parm-value", tags=("large", "parm", "value"))


class NoResourceWrites:
    def put_bytes(self, _payload: bytes):
        pytest.fail("Inline or invalid parameter changes must not create Resources")


def _parm_change(*, before: object = "a", after: object = "b") -> dict[str, object]:
    return {
        "type": "parm_changed",
        "node": 11,
        "path": "/obj/final",
        "parm": "text",
        "before": before,
        "after": after,
    }


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


@pytest.mark.parametrize("present_side", ["before", "after"])
@pytest.mark.parametrize(
    "raw_value",
    ["", "$HIP/raw.$F", "null"],
    ids=["empty", "expression", "literal-null"],
)
def test_parameter_absence_remains_distinct_from_present_raw_strings(
    present_side: str, raw_value: str
) -> None:
    raw = _parm_change(before=None, after=None)
    raw[present_side] = raw_value

    change = materialize_action_changes([raw], resources=NoResourceWrites())[0]  # type: ignore[arg-type]

    assert isinstance(change, ParmChangedChange)
    assert change.to_payload() == raw


@pytest.mark.parametrize("invalid_keys", ["missing-before", "missing-after", "extra"])
def test_parameter_change_requires_exact_keys(invalid_keys: str) -> None:
    raw = _parm_change()
    if invalid_keys == "extra":
        raw["unexpected"] = None
    else:
        del raw[invalid_keys.removeprefix("missing-")]

    with pytest.raises(BridgeError) as caught:
        materialize_action_changes([raw], resources=NoResourceWrites())  # type: ignore[arg-type]
    assert caught.value.code == "history_change_invalid"


def test_parameter_change_rejects_two_absent_sides() -> None:
    with pytest.raises(BridgeError) as caught:
        materialize_action_changes(
            [_parm_change(before=None, after=None)],
            resources=NoResourceWrites(),  # type: ignore[arg-type]
        )
    assert caught.value.code == "history_change_invalid"


@pytest.mark.parametrize("side", ["before", "after"])
@pytest.mark.parametrize(
    "invalid_value",
    [
        pytest.param(0, id="integer"),
        pytest.param(1.5, id="float"),
        pytest.param(False, id="false"),
        pytest.param(True, id="true"),
        pytest.param(["text"], id="array"),
        pytest.param({}, id="object"),
        pytest.param(
            {"omitted": True, "resource": "large-parm-value-000", "tokens": 9138},
            id="public-omission",
        ),
        pytest.param(b"text", id="bytes"),
        pytest.param(("text",), id="tuple"),
    ],
)
def test_parameter_change_rejects_unsupported_raw_side_types(
    side: str, invalid_value: object
) -> None:
    raw = _parm_change()
    raw[side] = invalid_value

    with pytest.raises(BridgeError) as caught:
        materialize_action_changes([raw], resources=NoResourceWrites())  # type: ignore[arg-type]
    assert caught.value.code == "history_change_invalid"


@pytest.mark.parametrize("present_side", ["before", "after"])
@pytest.mark.parametrize(
    ("raw_value", "resource_mime"),
    [
        pytest.param("x" * 4096, None, id="ascii-4096"),
        pytest.param("x" * 4097, "text/plain", id="ascii-4097"),
        pytest.param("多" * 1365 + "x", None, id="multibyte-4096"),
        pytest.param("多" * 1366, "text/plain", id="multibyte-4098"),
        pytest.param(
            '{"expression":"' + "x" * 4100 + '"}',
            "application/json",
            id="oversized-json",
        ),
    ],
)
def test_membership_present_side_uses_existing_utf8_resource_bound(
    tmp_path: Path,
    monkeypatch,
    present_side: str,
    raw_value: str,
    resource_mime: str | None,
) -> None:
    resources = _store(tmp_path, monkeypatch)
    writes: list[bytes] = []
    original_put = resources.put_bytes

    def put_bytes(payload: bytes):
        writes.append(payload)
        return original_put(payload)

    monkeypatch.setattr(resources, "put_bytes", put_bytes)
    raw = _parm_change(before=None, after=None)
    raw[present_side] = raw_value
    payload = materialize_action_changes([raw], resources=resources)[0].to_payload()
    absent_side = "after" if present_side == "before" else "before"

    assert set(payload) == {"type", "node", "path", "parm", "before", "after"}
    assert payload[absent_side] is None
    if resource_mime is None:
        assert payload == raw
        assert writes == []
    else:
        omitted = payload[present_side]
        assert isinstance(omitted, dict)
        assert set(omitted) == {"omitted", "resource", "tokens"}
        assert omitted["omitted"] is True
        resource = resources.get(omitted["resource"])
        assert resource is not None
        assert omitted["tokens"] == resource.token_count
        assert resource.mime == resource_mime
        assert resources.get_bytes(resource.semantic_alias) == raw_value.encode("utf-8")
        assert writes == [raw_value.encode("utf-8")]
