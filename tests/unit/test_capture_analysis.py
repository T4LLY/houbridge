from __future__ import annotations

from pathlib import Path

import pytest

from houbridge.capture.analysis import build_analysis_request, validate_analysis_preset
from houbridge.capture.models import AttributeVisualizerPreset, ScreenshotPreset
from houbridge.errors import BridgeError


def test_beauty_builds_no_analysis_request() -> None:
    assert build_analysis_request() is None
    assert build_analysis_request("beauty") is None


def test_analysis_request_normalizes_models_and_curvature_defaults() -> None:
    request = build_analysis_request(
        "curvature",
        model_paths=(" /obj/a ", "/obj/b"),
    )

    assert request is not None
    assert request.capture_pass == "curvature"
    assert request.model_paths == ("/obj/a", "/obj/b")
    assert request.curvature_scale == 1.0
    assert request.curvature_colormap == "rg"
    assert request.to_dict() == {
        "pass": "curvature",
        "model_paths": ["/obj/a", "/obj/b"],
        "unit": None,
        "curvature_scale": 1.0,
        "curvature_colormap": "rg",
    }


@pytest.mark.parametrize("value", ["", "beauties", "wireframe", object()])
def test_analysis_request_rejects_invalid_pass(value: object) -> None:
    with pytest.raises(BridgeError) as caught:
        build_analysis_request(value)  # type: ignore[arg-type]

    assert caught.value.code == "invalid_capture_pass"


def test_grid_requires_positive_finite_unit() -> None:
    with pytest.raises(BridgeError) as missing:
        build_analysis_request("grid")
    with pytest.raises(BridgeError) as zero:
        build_analysis_request("grid", unit=0)
    with pytest.raises(BridgeError) as infinity:
        build_analysis_request("grid", unit=float("inf"))

    assert missing.value.code == "grid_unit_required"
    assert zero.value.code == "invalid_grid_unit"
    assert infinity.value.code == "invalid_grid_unit"
    assert build_analysis_request("grid", unit=0.25).grid_unit == 0.25  # type: ignore[union-attr]


def test_mode_specific_options_are_not_silently_ignored() -> None:
    with pytest.raises(BridgeError) as beauty_model:
        build_analysis_request("beauty", model_paths=("/obj/a",))
    with pytest.raises(BridgeError) as normal_unit:
        build_analysis_request("normal", unit=1.0)
    with pytest.raises(BridgeError) as depth_curvature:
        build_analysis_request("depth", curvature_scale=2.0)

    assert beauty_model.value.code == "capture_pass_option_conflict"
    assert normal_unit.value.code == "capture_pass_option_conflict"
    assert depth_curvature.value.code == "capture_pass_option_conflict"


def test_curvature_validates_scale_and_colormap() -> None:
    with pytest.raises(BridgeError) as scale:
        build_analysis_request("curvature", curvature_scale=float("nan"))
    with pytest.raises(BridgeError) as colormap:
        build_analysis_request("curvature", curvature_colormap="rb")

    assert scale.value.code == "invalid_curvature_scale"
    assert colormap.value.code == "invalid_curvature_colormap"

    request = build_analysis_request(
        "curvature",
        curvature_scale=2.0,
        curvature_colormap="gray",
    )
    assert request is not None
    assert request.curvature_scale == 2.0
    assert request.curvature_colormap == "gray"


def test_model_paths_must_be_absolute() -> None:
    with pytest.raises(BridgeError) as relative:
        build_analysis_request("normal", model_paths=("obj/a",))
    with pytest.raises(BridgeError) as root:
        build_analysis_request("normal", model_paths=("/",))

    assert relative.value.code == "capture_model_invalid"
    assert root.value.code == "capture_model_invalid"


def test_analysis_preset_allows_view_only() -> None:
    validate_analysis_preset(ScreenshotPreset(view="front"))

    invalid = [
        ScreenshotPreset(shading="smooth"),
        ScreenshotPreset(overlays=(("point_markers", True),)),
        ScreenshotPreset(attributes=(AttributeVisualizerPreset("point", "Cd"),)),
        ScreenshotPreset(crop="network_editor"),
    ]
    for preset in invalid:
        with pytest.raises(BridgeError) as caught:
            validate_analysis_preset(preset)
        assert caught.value.code == "capture_analysis_preset_invalid"
