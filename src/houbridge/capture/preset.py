from __future__ import annotations

import json
from pathlib import Path

from houbridge.errors import BridgeError

from .models import (
    AttributeVisualizerPreset,
    ScreenshotMode,
    ScreenshotPreset,
    ScreenshotView,
)


_ALLOWED_VIEWS = {"top", "bottom", "front", "back", "left", "right", "persp", "uv"}
_ALLOWED_SHADING = {
    "wire",
    "wireghost",
    "hiddenline",
    "hiddenlineghost",
    "flat",
    "flatwire",
    "smooth",
    "smoothwire",
    "matcap",
    "matcapwire",
}
_ALLOWED_OVERLAYS = {
    "point_markers",
    "point_numbers",
    "point_normals",
    "point_uvs",
    "point_positions",
    "prim_numbers",
    "prim_normals",
    "vertex_markers",
    "vertex_numbers",
    "vertex_normals",
    "vertex_uvs",
    "uv_backfaces",
    "uv_overlap",
}
_ALLOWED_ATTRIBUTE_CLASSES = {"point", "prim", "vertex", "detail"}
_ALLOWED_TOP_LEVEL = {"view", "shading", "overlays", "attributes", "crop"}


def load_screenshot_preset(path: Path, *, mode: ScreenshotMode) -> ScreenshotPreset:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise BridgeError(
            "invalid_screenshot_preset",
            f"Unable to read screenshot preset JSON: {path}",
        ) from exc
    if not isinstance(raw, dict):
        raise BridgeError(
            "invalid_screenshot_preset",
            "Screenshot preset root must be an object.",
        )

    unknown = set(raw) - _ALLOWED_TOP_LEVEL
    if unknown:
        raise BridgeError(
            "invalid_screenshot_preset",
            "Unsupported screenshot preset keys: " + ", ".join(sorted(unknown)),
        )

    view_value = raw.get("view")
    view = None if view_value is None else validate_screenshot_view(view_value)

    shading_raw = raw.get("shading")
    shading: str | None = None
    if shading_raw is not None:
        if not isinstance(shading_raw, str) or shading_raw.lower() not in _ALLOWED_SHADING:
            raise BridgeError(
                "invalid_screenshot_preset",
                "Screenshot preset shading is unsupported.",
            )
        shading = shading_raw.lower()

    overlays_raw = raw.get("overlays", {})
    if not isinstance(overlays_raw, dict):
        raise BridgeError(
            "invalid_screenshot_preset",
            "Screenshot preset overlays must be an object.",
        )
    unknown_overlays = set(overlays_raw) - _ALLOWED_OVERLAYS
    if unknown_overlays:
        raise BridgeError(
            "invalid_screenshot_preset",
            "Unsupported screenshot overlay keys: "
            + ", ".join(sorted(unknown_overlays)),
        )
    overlays: list[tuple[str, bool]] = []
    for name, enabled in overlays_raw.items():
        if not isinstance(enabled, bool):
            raise BridgeError(
                "invalid_screenshot_preset",
                f"Screenshot overlay {name} must be a boolean.",
            )
        overlays.append((name, enabled))

    attributes_raw = raw.get("attributes", [])
    if not isinstance(attributes_raw, list):
        raise BridgeError(
            "invalid_screenshot_preset",
            "Screenshot preset attributes must be an array.",
        )
    attributes: list[AttributeVisualizerPreset] = []
    for item in attributes_raw:
        if not isinstance(item, dict) or set(item) != {"class", "name"}:
            raise BridgeError(
                "invalid_screenshot_preset",
                "Each screenshot attribute must contain exactly class and name.",
            )
        attribute_class = item.get("class")
        name = item.get("name")
        if not isinstance(attribute_class, str) or attribute_class not in _ALLOWED_ATTRIBUTE_CLASSES:
            raise BridgeError(
                "invalid_screenshot_preset",
                "Screenshot attribute class must be point, prim, vertex, or detail.",
            )
        if not isinstance(name, str) or not name.strip():
            raise BridgeError(
                "invalid_screenshot_preset",
                "Screenshot attribute name must be a non-empty string.",
            )
        attributes.append(AttributeVisualizerPreset(attribute_class, name.strip()))

    crop_raw = raw.get("crop")
    crop: str | None = None
    if crop_raw is not None:
        if not isinstance(crop_raw, str) or not crop_raw.strip():
            raise BridgeError(
                "invalid_screenshot_preset",
                "Screenshot preset crop must be a non-empty string.",
            )
        crop = crop_raw.strip()

    preset = ScreenshotPreset(
        view=view,
        shading=shading,
        overlays=tuple(sorted(overlays)),
        attributes=tuple(attributes),
        crop=crop,
    )
    _validate_mode(preset, mode=mode)
    return preset


def validate_screenshot_view(value: object) -> ScreenshotView:
    if not isinstance(value, str) or value.lower() not in _ALLOWED_VIEWS:
        raise BridgeError(
            "invalid_screenshot_view",
            "Screenshot view must be top, bottom, front, back, left, right, persp, or uv.",
        )
    return value.lower()  # type: ignore[return-value]


def _validate_mode(preset: ScreenshotPreset, *, mode: ScreenshotMode) -> None:
    if mode == "viewport":
        if preset.crop is not None:
            raise BridgeError(
                "screenshot_crop_requires_window",
                "Screenshot crop presets are only valid for window capture.",
            )
        return
    if mode == "window":
        if (
            preset.view is not None
            or preset.shading is not None
            or preset.overlays
            or preset.attributes
        ):
            raise BridgeError(
                "screenshot_window_preset_invalid",
                "Window screenshot presets may only configure crop.",
            )
        return
    if mode == "turntable":
        if preset.view is not None or preset.crop is not None:
            raise BridgeError(
                "turntable_preset_invalid",
                "Turntable screenshot presets may configure only shading, overlays, and attributes.",
            )
        return
    raise ValueError(f"Unsupported screenshot preset mode: {mode}")
