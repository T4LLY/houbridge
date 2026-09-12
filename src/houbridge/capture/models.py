from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


ScreenshotView = Literal[
    "top",
    "bottom",
    "front",
    "back",
    "left",
    "right",
    "persp",
    "uv",
]
ScreenshotMode = Literal["viewport", "window", "turntable"]
ScreenshotKind = Literal["viewport", "window"]


@dataclass(frozen=True, slots=True)
class AttributeVisualizerPreset:
    attribute_class: str
    name: str

    def to_dict(self) -> dict[str, str]:
        return {"class": self.attribute_class, "name": self.name}


@dataclass(frozen=True, slots=True)
class ScreenshotPreset:
    view: ScreenshotView | None = None
    shading: str | None = None
    overlays: tuple[tuple[str, bool], ...] = ()
    attributes: tuple[AttributeVisualizerPreset, ...] = ()
    crop: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "view": self.view,
            "shading": self.shading,
            "overlays": dict(self.overlays),
            "attributes": [item.to_dict() for item in self.attributes],
            "crop": self.crop,
        }
