from __future__ import annotations

import json
from pathlib import Path

import pytest

from houbridge.capture.preset import load_screenshot_preset, validate_screenshot_view
from houbridge.errors import BridgeError


def test_preset_accepts_only_current_viewport_contract(tmp_path: Path) -> None:
    path = tmp_path / "preset.json"
    path.write_text(
        json.dumps(
            {
                "view": "UV",
                "shading": "SmoothWire",
                "overlays": {"point_numbers": True, "vertex_uvs": False},
                "attributes": [
                    {"class": "point", "name": " mass "},
                    {"class": "prim", "name": "name"},
                ],
            }
        ),
        encoding="utf-8",
    )

    preset = load_screenshot_preset(path, mode="viewport")

    assert preset.view == "uv"
    assert preset.shading == "smoothwire"
    assert dict(preset.overlays) == {"point_numbers": True, "vertex_uvs": False}
    assert [item.to_dict() for item in preset.attributes] == [
        {"class": "point", "name": "mass"},
        {"class": "prim", "name": "name"},
    ]


@pytest.mark.parametrize(
    ("payload", "code"),
    [
        ({"unknown": True}, "invalid_screenshot_preset"),
        ({"view": "sideways"}, "invalid_screenshot_view"),
        ({"shading": "beauty"}, "invalid_screenshot_preset"),
        ({"overlays": {"unknown": True}}, "invalid_screenshot_preset"),
        ({"overlays": {"point_numbers": 1}}, "invalid_screenshot_preset"),
        ({"attributes": [{"class": "point", "name": "P", "extra": 1}]}, "invalid_screenshot_preset"),
        ({"attributes": [{"class": "object", "name": "P"}]}, "invalid_screenshot_preset"),
        ({"crop": "   "}, "invalid_screenshot_preset"),
    ],
)
def test_preset_rejects_unknown_or_malformed_values(
    tmp_path: Path,
    payload: dict[str, object],
    code: str,
) -> None:
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(BridgeError) as caught:
        load_screenshot_preset(path, mode="viewport")

    assert caught.value.code == code


def test_mode_specific_preset_capabilities_are_enforced(tmp_path: Path) -> None:
    crop = tmp_path / "crop.json"
    crop.write_text('{"crop":"network_editor"}', encoding="utf-8")
    display = tmp_path / "display.json"
    display.write_text('{"shading":"smooth"}', encoding="utf-8")
    view = tmp_path / "view.json"
    view.write_text('{"view":"front"}', encoding="utf-8")

    with pytest.raises(BridgeError) as viewport:
        load_screenshot_preset(crop, mode="viewport")
    with pytest.raises(BridgeError) as window:
        load_screenshot_preset(display, mode="window")
    with pytest.raises(BridgeError) as turntable:
        load_screenshot_preset(view, mode="turntable")

    assert viewport.value.code == "screenshot_crop_requires_window"
    assert window.value.code == "screenshot_window_preset_invalid"
    assert turntable.value.code == "turntable_preset_invalid"


def test_window_crop_is_trimmed_and_turntable_display_settings_are_allowed(tmp_path: Path) -> None:
    crop = tmp_path / "crop.json"
    crop.write_text('{"crop":"  viewport:persp:0  "}', encoding="utf-8")
    turntable = tmp_path / "turntable.json"
    turntable.write_text(
        '{"shading":"flat","overlays":{"point_markers":true},"attributes":[]}',
        encoding="utf-8",
    )

    assert load_screenshot_preset(crop, mode="window").crop == "viewport:persp:0"
    assert load_screenshot_preset(turntable, mode="turntable").shading == "flat"


def test_view_validator_is_case_insensitive_but_does_not_invent_aliases() -> None:
    assert validate_screenshot_view("FrOnT") == "front"
    with pytest.raises(BridgeError) as caught:
        validate_screenshot_view("perspective")
    assert caught.value.code == "invalid_screenshot_view"
