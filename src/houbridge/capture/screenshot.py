from __future__ import annotations

from dataclasses import replace
from datetime import datetime
import json
import math
from pathlib import Path

from houbridge.config import ScreenshotConfig
from houbridge.errors import BridgeError
from houbridge.houdini.transport import HoudiniTransport
from houbridge.session.resolver import ResolvedSession
from houbridge.temporary_workspace import TemporaryWorkspaceService

from ._injected import write_runpy_runner
from .artifacts import CaptureArtifactPublisher
from .models import ScreenshotKind, ScreenshotPreset
from .png import png_size
from .preset import load_screenshot_preset, validate_screenshot_view


class ScreenshotService:
    def __init__(
        self,
        transport: HoudiniTransport,
        screenshot_config: ScreenshotConfig,
        publisher: CaptureArtifactPublisher,
        *,
        workspaces: TemporaryWorkspaceService | None = None,
        script_path: Path | None = None,
    ) -> None:
        self._transport = transport
        self._config = screenshot_config
        self._publisher = publisher
        self._workspaces = workspaces or TemporaryWorkspaceService()
        if script_path is None:
            from houbridge.houdini.scripts.capture import screenshot

            script_path = Path(screenshot.__file__)
        self._script_path = script_path.resolve()

    def capture_viewport(
        self,
        session: ResolvedSession,
        *,
        views: tuple[str, ...] = (),
        scale: float = 1.0,
        preset_path: Path | None = None,
        pane: str | None = None,
    ) -> dict[str, object]:
        _validate_scale(scale)
        preset = (
            load_screenshot_preset(preset_path, mode="viewport")
            if preset_path is not None
            else ScreenshotPreset()
        )
        normalized_views = tuple(validate_screenshot_view(view) for view in views)
        effective_views = normalized_views
        if not effective_views and preset.view is not None:
            effective_views = (preset.view,)
        capture_labels = effective_views or ("active",)
        published = self._capture(
            session,
            kind="viewport",
            labels=capture_labels,
            requested_views=effective_views,
            scale=scale,
            preset=preset,
            bounds=False,
            pane=pane,
        )
        paths, _bounds = published
        if len(paths) == 1:
            return {"path": str(paths[0])}
        return {
            "captures": [
                {"view": view, "path": str(path)}
                for view, path in zip(capture_labels, paths, strict=True)
            ]
        }

    def capture_window(
        self,
        session: ResolvedSession,
        *,
        scale: float = 1.0,
        crop: str | None = None,
        preset_path: Path | None = None,
    ) -> dict[str, object]:
        _validate_scale(scale)
        preset = (
            load_screenshot_preset(preset_path, mode="window")
            if preset_path is not None
            else ScreenshotPreset()
        )
        if crop is not None:
            effective_crop = crop.strip()
            if not effective_crop:
                raise BridgeError(
                    "invalid_screenshot_crop",
                    "Screenshot crop selector must be a non-empty string.",
                )
        else:
            effective_crop = preset.crop
        preset = replace(preset, crop=effective_crop)
        paths, bounds = self._capture(
            session,
            kind="window",
            labels=("window",),
            requested_views=(),
            scale=scale,
            preset=preset,
            bounds=True,
            pane=None,
        )
        if bounds is None:
            raise BridgeError("screenshot_failed", "Window screenshot bounds are missing.")
        return {"path": str(paths[0]), "bounds": bounds}

    def _capture(
        self,
        session: ResolvedSession,
        *,
        kind: ScreenshotKind,
        labels: tuple[str, ...],
        requested_views: tuple[str, ...],
        scale: float,
        preset: ScreenshotPreset,
        bounds: bool,
        pane: str | None,
    ) -> tuple[tuple[Path, ...], dict[str, object] | None]:
        workspace = self._workspaces.allocate(prefix=f"capture-{kind}")
        published: list[Path] = []
        try:
            png_paths = tuple(
                workspace.path_for(f"capture-{index:03d}.png")
                for index in range(len(labels))
            )
            bounds_path = workspace.path_for("bounds.json") if bounds else None
            result_path = workspace.path_for("result.json")
            request_path = workspace.path_for("request.json")
            request_path.write_text(
                json.dumps(
                    {
                        "kind": kind,
                        "png_paths": [str(path) for path in png_paths],
                        "bounds_path": str(bounds_path) if bounds_path is not None else None,
                        "result_path": str(result_path),
                        "requested_views": list(requested_views),
                        "scale": scale,
                        "max_width": self._config.max_width,
                        "max_height": self._config.max_height,
                        "preset": preset.to_dict(),
                        "pane": pane,
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                encoding="utf-8",
            )
            runner = write_runpy_runner(
                workspace,
                script_path=self._script_path,
                request_path=request_path,
                filename="screenshot.py",
            )
            self._transport.execute_script(session.target, runner)
            _require_capture_success(result_path)

            for path in png_paths:
                if not path.is_file():
                    raise BridgeError(
                        "screenshot_failed",
                        "Screenshot status succeeded but PNG is missing.",
                    )
                width, height = png_size(path)
                if width > self._config.max_width or height > self._config.max_height:
                    raise BridgeError(
                        "screenshot_failed",
                        "Screenshot output exceeded the configured maximum dimensions.",
                    )

            parsed_bounds = None
            if bounds_path is not None:
                parsed_bounds = _read_bounds(
                    bounds_path,
                    png_paths[0],
                    cropped_from=preset.crop,
                )

            self._publisher.cleanup_expired()
            captured_at = self._publisher.now_datetime()
            published = [
                self._publisher.publish_png(path, kind=kind, captured_at=captured_at)
                for path in png_paths
            ]
            return tuple(published), parsed_bounds
        except BridgeError:
            for path in published:
                path.unlink(missing_ok=True)
            raise
        except (OSError, ValueError) as exc:
            for path in published:
                path.unlink(missing_ok=True)
            raise BridgeError(
                "screenshot_failed",
                "Screenshot capture failed.",
                f"{type(exc).__name__}: {exc}",
            ) from exc
        finally:
            workspace.remove()


def _validate_scale(scale: float) -> None:
    if isinstance(scale, bool) or not isinstance(scale, (int, float)):
        raise BridgeError("invalid_screenshot_scale", "Screenshot scale must be greater than zero.")
    if not math.isfinite(float(scale)) or float(scale) <= 0:
        raise BridgeError("invalid_screenshot_scale", "Screenshot scale must be greater than zero.")


def _require_capture_success(path: Path) -> None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise BridgeError(
            "screenshot_failed",
            "Houdini returned without writing screenshot status.",
        ) from exc
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise BridgeError(
            "screenshot_failed",
            "Screenshot status is unreadable or invalid JSON.",
            f"{type(exc).__name__}: {exc}",
        ) from exc
    if not isinstance(payload, dict) or (payload.get("ok") is not True and payload.get("ok") is not False):
        raise BridgeError("screenshot_failed", "Screenshot status is invalid.")
    if payload.get("ok") is False:
        message = payload.get("message")
        detail = payload.get("detail")
        code = payload.get("code")
        context = payload.get("context")
        if code is not None and (not isinstance(code, str) or not code):
            raise BridgeError(
                "screenshot_failed",
                "Screenshot status contains an invalid error code.",
            )
        if context is not None and not isinstance(context, dict):
            raise BridgeError(
                "screenshot_failed",
                "Screenshot status contains invalid error context.",
            )
        raise BridgeError(
            code or "screenshot_failed",
            str(message) if isinstance(message, str) and message else "Screenshot capture failed inside Houdini.",
            str(detail)[:4096] if isinstance(detail, str) and detail else None,
            context=context,
        )


def _read_bounds(
    path: Path,
    png_path: Path,
    *,
    cropped_from: str | None,
) -> dict[str, object]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise BridgeError(
            "screenshot_failed",
            "Window screenshot succeeded but UI bounds JSON is missing.",
        ) from exc
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise BridgeError(
            "screenshot_failed",
            "Window UI bounds JSON is unreadable or invalid.",
            f"{type(exc).__name__}: {exc}",
        ) from exc
    if not isinstance(raw, dict):
        raise BridgeError("screenshot_failed", "Window UI bounds JSON is not an object.")

    required = {
        "width",
        "height",
        "coordinate_space",
        "source_width",
        "source_height",
        "scale_x",
        "scale_y",
        "areas",
    }
    allowed = required | {"cropped_from"}
    if set(raw) - allowed or not required.issubset(raw):
        raise BridgeError("screenshot_failed", "Window UI bounds JSON has invalid fields.")
    width, height = png_size(png_path)
    if raw.get("width") != width or raw.get("height") != height:
        raise BridgeError(
            "screenshot_failed",
            "Window UI bounds dimensions do not match the final PNG.",
        )
    if raw.get("coordinate_space") != "final_png_top_left":
        raise BridgeError("screenshot_failed", "Window UI bounds coordinate space is invalid.")
    _require_positive_int(raw.get("source_width"), "source_width")
    _require_positive_int(raw.get("source_height"), "source_height")
    _require_positive_number(raw.get("scale_x"), "scale_x")
    _require_positive_number(raw.get("scale_y"), "scale_y")
    areas_raw = raw.get("areas")
    if not isinstance(areas_raw, list):
        raise BridgeError("screenshot_failed", "Window UI bounds JSON has no areas array.")
    areas = [_normalize_area(item) for item in areas_raw]

    if cropped_from is None:
        if "cropped_from" in raw:
            raise BridgeError("screenshot_failed", "Unexpected cropped_from in window bounds.")
    elif raw.get("cropped_from") != cropped_from:
        raise BridgeError("screenshot_failed", "Window crop selector does not match bounds metadata.")

    normalized: dict[str, object] = {
        "width": width,
        "height": height,
        "coordinate_space": "final_png_top_left",
        "source_width": raw["source_width"],
        "source_height": raw["source_height"],
        "scale_x": raw["scale_x"],
        "scale_y": raw["scale_y"],
        "areas": areas,
    }
    if cropped_from is not None:
        normalized["cropped_from"] = cropped_from
    return normalized


def _normalize_area(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise BridgeError("screenshot_failed", "Window UI bounds area is invalid.")
    required = {"type", "name", "x", "y", "width", "height"}
    allowed = required | {"viewports"}
    if set(value) - allowed or not required.issubset(value):
        raise BridgeError("screenshot_failed", "Window UI bounds area has invalid fields.")
    if not isinstance(value["type"], str) or not isinstance(value["name"], str):
        raise BridgeError("screenshot_failed", "Window UI bounds area identity is invalid.")
    result: dict[str, object] = {"type": value["type"], "name": value["name"]}
    for key in ("x", "y", "width", "height"):
        _require_nonnegative_int(value[key], key)
        result[key] = value[key]
    if "viewports" in value:
        viewports_raw = value["viewports"]
        if not isinstance(viewports_raw, list):
            raise BridgeError("screenshot_failed", "Window viewport bounds are invalid.")
        result["viewports"] = [_normalize_viewport(item) for item in viewports_raw]
    return result


def _normalize_viewport(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != {"type", "name", "x", "y", "width", "height"}:
        raise BridgeError("screenshot_failed", "Window viewport bounds are invalid.")
    if not isinstance(value["type"], str) or not isinstance(value["name"], str):
        raise BridgeError("screenshot_failed", "Window viewport bounds identity is invalid.")
    result: dict[str, object] = {"type": value["type"], "name": value["name"]}
    for key in ("x", "y", "width", "height"):
        _require_nonnegative_int(value[key], key)
        result[key] = value[key]
    return result


def _require_positive_int(value: object, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise BridgeError("screenshot_failed", f"Window UI bounds {label} is invalid.")


def _require_nonnegative_int(value: object, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise BridgeError("screenshot_failed", f"Window UI bounds {label} is invalid.")


def _require_positive_number(value: object, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise BridgeError("screenshot_failed", f"Window UI bounds {label} is invalid.")
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise BridgeError("screenshot_failed", f"Window UI bounds {label} is invalid.")
