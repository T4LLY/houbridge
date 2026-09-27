from __future__ import annotations

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
from .png import png_size


class CameraService:
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
            from houbridge.houdini.scripts.capture import camera

            script_path = Path(camera.__file__)
        self._script_path = script_path.resolve()

    def list(self, session: ResolvedSession) -> dict[str, object]:
        payload = self._execute(session, {"mode": "list"}, prefix="capture-camera-list")
        return _normalize_camera_list(payload)

    def detail(self, session: ResolvedSession, camera_path: str) -> dict[str, object]:
        path = _validate_camera_path(camera_path)
        payload = self._execute(
            session,
            {"mode": "detail", "camera_path": path},
            prefix="capture-camera-detail",
        )
        _require_success_payload(payload, expected_fields={"ok", "camera"})
        return _normalize_camera_detail(payload.get("camera"))

    def capture(
        self,
        session: ResolvedSession,
        camera_path: str,
        *,
        scale: float = 1.0,
        pane: str | None = None,
    ) -> dict[str, str]:
        path = _validate_camera_path(camera_path)
        _validate_scale(scale)
        workspace = self._workspaces.allocate(prefix="capture-camera")
        published: Path | None = None
        try:
            png_path = workspace.path_for("camera.png")
            payload = self._execute_in_workspace(
                session,
                workspace,
                {
                    "mode": "capture",
                    "camera_path": path,
                    "png_path": str(png_path),
                    "scale": float(scale),
                    "max_width": self._config.max_width,
                    "max_height": self._config.max_height,
                    "pane": pane,
                },
            )
            _require_success_payload(payload, expected_fields={"ok"})
            if not png_path.is_file():
                raise BridgeError(
                    "camera_capture_failed",
                    "Camera capture status succeeded but PNG is missing.",
                )
            width, height = png_size(png_path)
            if width > self._config.max_width or height > self._config.max_height:
                raise BridgeError(
                    "camera_capture_failed",
                    "Camera capture exceeded the configured maximum dimensions.",
                )
            self._publisher.cleanup_expired()
            published = self._publisher.publish_png(png_path, kind="camera")
            return {"path": str(published)}
        except BridgeError:
            if published is not None:
                published.unlink(missing_ok=True)
            raise
        except (OSError, ValueError) as exc:
            if published is not None:
                published.unlink(missing_ok=True)
            raise BridgeError(
                "camera_capture_failed",
                "Camera capture failed.",
                f"{type(exc).__name__}: {exc}",
            ) from exc
        finally:
            workspace.remove()

    def _execute(
        self,
        session: ResolvedSession,
        request: dict[str, object],
        *,
        prefix: str,
    ) -> dict[str, object]:
        workspace = self._workspaces.allocate(prefix=prefix)
        try:
            return self._execute_in_workspace(session, workspace, request)
        finally:
            workspace.remove()

    def _execute_in_workspace(
        self,
        session: ResolvedSession,
        workspace,
        request: dict[str, object],
    ) -> dict[str, object]:
        result_path = workspace.path_for("result.json")
        request_path = workspace.path_for("request.json")
        request_path.write_text(
            json.dumps(
                {**request, "result_path": str(result_path)},
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            encoding="utf-8",
        )
        runner = write_runpy_runner(
            workspace,
            script_path=self._script_path,
            request_path=request_path,
            filename="camera.py",
        )
        self._transport.execute_script(session.target, runner)
        return _read_camera_result(result_path)


def _validate_camera_path(value: str) -> str:
    path = value.strip()
    if not path or not path.startswith("/"):
        raise BridgeError(
            "camera_path_invalid",
            "Camera path must be an absolute Houdini node path.",
        )
    return path


def _validate_scale(value: float) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise BridgeError(
            "invalid_screenshot_scale",
            "Screenshot scale must be greater than zero.",
        )
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise BridgeError(
            "invalid_screenshot_scale",
            "Screenshot scale must be greater than zero.",
        )


def _read_camera_result(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise BridgeError(
            "camera_failed",
            "Houdini returned without writing camera status.",
        ) from exc
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise BridgeError(
            "camera_failed",
            "Camera status is unreadable or invalid JSON.",
            f"{type(exc).__name__}: {exc}",
        ) from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("ok"), bool):
        raise BridgeError("camera_failed", "Camera status has an invalid shape.")
    if payload["ok"]:
        return payload

    code = payload.get("code")
    message = payload.get("message")
    detail = payload.get("detail")
    context = payload.get("context")
    if code is not None and (not isinstance(code, str) or not code):
        raise BridgeError("camera_failed", "Camera status contains an invalid error code.")
    if context is not None and not isinstance(context, dict):
        raise BridgeError("camera_failed", "Camera status contains invalid error context.")
    raise BridgeError(
        code or "camera_failed",
        message if isinstance(message, str) and message else "Camera operation failed inside Houdini.",
        detail[:4096] if isinstance(detail, str) and detail else None,
        context=context,
    )


def _normalize_camera_list(payload: dict[str, object]) -> dict[str, object]:
    _require_success_payload(payload, expected_fields={"ok", "cameras"})
    cameras = payload.get("cameras")
    if not isinstance(cameras, list):
        raise BridgeError("camera_info_invalid", "Camera list has no cameras array.")
    return {"cameras": [_normalize_camera_summary(item) for item in cameras]}


def _normalize_camera_summary(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != {"path", "type", "resolution"}:
        raise BridgeError("camera_info_invalid", "Camera list entry has invalid fields.")
    path = value.get("path")
    camera_type = value.get("type")
    resolution = value.get("resolution")
    if not isinstance(path, str) or camera_type not in {"obj", "sop"}:
        raise BridgeError("camera_info_invalid", "Camera list entry has invalid identity.")
    return {
        "path": path,
        "type": camera_type,
        "resolution": _normalize_resolution(resolution),
    }


def _normalize_camera_detail(value: object) -> dict[str, object]:
    required = {
        "path",
        "type",
        "resolution",
        "projection",
        "focal_length",
        "aperture",
        "pixel_aspect",
        "near_clip",
        "far_clip",
        "focus_distance",
        "f_stop",
    }
    if not isinstance(value, dict) or set(value) != required:
        raise BridgeError("camera_info_invalid", "Camera detail has invalid fields.")
    path = value.get("path")
    camera_type = value.get("type")
    projection = value.get("projection")
    if (
        not isinstance(path, str)
        or camera_type not in {"obj", "sop"}
        or not isinstance(projection, str)
    ):
        raise BridgeError("camera_info_invalid", "Camera detail has invalid identity.")
    result: dict[str, object] = {
        "path": path,
        "type": camera_type,
        "resolution": _normalize_resolution(value.get("resolution")),
        "projection": projection,
    }
    for key in (
        "focal_length",
        "aperture",
        "pixel_aspect",
        "near_clip",
        "far_clip",
        "focus_distance",
        "f_stop",
    ):
        item = value.get(key)
        if isinstance(item, bool) or not isinstance(item, (int, float)) or not math.isfinite(float(item)):
            raise BridgeError("camera_info_invalid", f"Camera detail {key} is invalid.")
        result[key] = float(item)
    return result


def _normalize_resolution(value: object) -> list[int]:
    if (
        not isinstance(value, list)
        or len(value) != 2
        or any(isinstance(item, bool) or not isinstance(item, int) or item <= 0 for item in value)
    ):
        raise BridgeError("camera_info_invalid", "Camera resolution is invalid.")
    return [value[0], value[1]]


def _require_success_payload(payload: dict[str, object], *, expected_fields: set[str]) -> None:
    if payload.get("ok") is not True or set(payload) != expected_fields:
        raise BridgeError("camera_failed", "Camera status has an invalid success envelope.")
