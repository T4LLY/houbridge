from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
from typing import Literal, Protocol

from houbridge.errors import BridgeError
from houbridge.session.resolver import ResolvedSession
from houbridge.temporary_workspace import TemporaryWorkspace

from .models import ScreenshotPreset

CapturePass = Literal["beauty", "depth", "grid", "normal", "object-id", "curvature"]
AnalysisPass = Literal["depth", "grid", "normal", "object-id", "curvature"]
CurvatureColormap = Literal["gray", "rg"]

_ALLOWED_PASSES = {"beauty", "depth", "grid", "normal", "object-id", "curvature"}
_ANALYSIS_PASSES = {"depth", "grid", "normal", "object-id", "curvature"}
_CURVATURE_COLORMAPS = {"gray", "rg"}


@dataclass(frozen=True, slots=True)
class AnalysisCaptureRequest:
    capture_pass: AnalysisPass
    model_paths: tuple[str, ...] = ()
    grid_unit: float | None = None
    curvature_scale: float = 1.0
    curvature_colormap: CurvatureColormap = "rg"

    def to_dict(self) -> dict[str, object]:
        return {
            "pass": self.capture_pass,
            "model_paths": list(self.model_paths),
            "unit": self.grid_unit,
            "curvature_scale": self.curvature_scale,
            "curvature_colormap": self.curvature_colormap,
        }


@dataclass(frozen=True, slots=True)
class ViewportAnalysisSource:
    png_paths: tuple[Path, ...]
    requested_views: tuple[str, ...]
    scale: float
    max_width: int
    max_height: int
    preset: ScreenshotPreset
    pane: str | None


@dataclass(frozen=True, slots=True)
class CameraAnalysisSource:
    png_path: Path
    camera_path: str
    scale: float
    max_width: int
    max_height: int
    pane: str | None


class AnalysisCaptureBackend(Protocol):
    def render_viewport(
        self,
        session: ResolvedSession,
        request: AnalysisCaptureRequest,
        source: ViewportAnalysisSource,
        workspace: TemporaryWorkspace,
    ) -> None: ...

    def render_camera(
        self,
        session: ResolvedSession,
        request: AnalysisCaptureRequest,
        source: CameraAnalysisSource,
        workspace: TemporaryWorkspace,
    ) -> None: ...


def build_analysis_request(
    capture_pass: str = "beauty",
    *,
    model_paths: tuple[str, ...] = (),
    unit: float | None = None,
    curvature_scale: float | None = None,
    curvature_colormap: str | None = None,
) -> AnalysisCaptureRequest | None:
    normalized_pass = _validate_capture_pass(capture_pass)
    normalized_models = _validate_model_paths(model_paths)

    if normalized_pass == "beauty":
        if normalized_models:
            raise BridgeError(
                "capture_pass_option_conflict",
                "--model is valid only with a non-beauty capture pass.",
            )
        if unit is not None:
            raise BridgeError(
                "capture_pass_option_conflict",
                "--unit is only valid with --pass grid.",
            )
        if curvature_scale is not None or curvature_colormap is not None:
            raise BridgeError(
                "capture_pass_option_conflict",
                "Curvature options are valid only with --pass curvature.",
            )
        return None

    if normalized_pass == "grid":
        normalized_unit = _positive_finite(
            unit,
            code="invalid_grid_unit",
            message="Grid unit must be a finite number greater than zero.",
            required_code="grid_unit_required",
            required_message="--unit is required with --pass grid.",
        )
    else:
        if unit is not None:
            raise BridgeError(
                "capture_pass_option_conflict",
                "--unit is only valid with --pass grid.",
            )
        normalized_unit = None

    if normalized_pass == "curvature":
        normalized_scale = _positive_finite(
            1.0 if curvature_scale is None else curvature_scale,
            code="invalid_curvature_scale",
            message="Curvature scale must be a finite number greater than zero.",
        )
        normalized_colormap = _validate_curvature_colormap(
            "rg" if curvature_colormap is None else curvature_colormap
        )
    else:
        if curvature_scale is not None or curvature_colormap is not None:
            raise BridgeError(
                "capture_pass_option_conflict",
                "Curvature options are valid only with --pass curvature.",
            )
        normalized_scale = 1.0
        normalized_colormap = "rg"

    return AnalysisCaptureRequest(
        capture_pass=normalized_pass,  # type: ignore[arg-type]
        model_paths=normalized_models,
        grid_unit=normalized_unit,
        curvature_scale=normalized_scale,
        curvature_colormap=normalized_colormap,
    )


def validate_analysis_preset(preset: ScreenshotPreset) -> None:
    if preset.shading is not None or preset.overlays or preset.attributes or preset.crop is not None:
        raise BridgeError(
            "capture_analysis_preset_invalid",
            "Non-beauty viewport presets may configure only view.",
        )


def _validate_capture_pass(value: object) -> CapturePass:
    if not isinstance(value, str):
        raise BridgeError(
            "invalid_capture_pass",
            "Capture pass must be beauty, depth, grid, normal, object-id, or curvature.",
        )
    normalized = value.strip().lower()
    if normalized not in _ALLOWED_PASSES:
        raise BridgeError(
            "invalid_capture_pass",
            "Capture pass must be beauty, depth, grid, normal, object-id, or curvature.",
        )
    return normalized  # type: ignore[return-value]


def _validate_model_paths(values: tuple[str, ...]) -> tuple[str, ...]:
    normalized: list[str] = []
    for value in values:
        if not isinstance(value, str):
            raise BridgeError(
                "capture_model_invalid",
                "Model paths must be absolute Houdini OBJ node paths.",
            )
        path = value.strip()
        if not path.startswith("/") or path == "/":
            raise BridgeError(
                "capture_model_invalid",
                "Model paths must be absolute Houdini OBJ node paths.",
            )
        normalized.append(path)
    return tuple(normalized)


def _positive_finite(
    value: object,
    *,
    code: str,
    message: str,
    required_code: str | None = None,
    required_message: str | None = None,
) -> float:
    if value is None and required_code is not None:
        raise BridgeError(required_code, required_message or message)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise BridgeError(code, message)
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise BridgeError(code, message)
    return number


def _validate_curvature_colormap(value: object) -> CurvatureColormap:
    if not isinstance(value, str):
        raise BridgeError(
            "invalid_curvature_colormap",
            "Curvature colormap must be gray or rg.",
        )
    normalized = value.strip().lower()
    if normalized not in _CURVATURE_COLORMAPS:
        raise BridgeError(
            "invalid_curvature_colormap",
            "Curvature colormap must be gray or rg.",
        )
    return normalized  # type: ignore[return-value]
