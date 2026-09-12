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
from .ffmpeg import encode_turntable_ffmpeg
from .models import ScreenshotPreset
from .png import png_size
from .preset import load_screenshot_preset


_DEFAULT_PIVOT = (0.0, 0.0, 0.0)


class TurntableService:
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
            from houbridge.houdini.scripts.capture import turntable

            script_path = Path(turntable.__file__)
        self._script_path = script_path.resolve()

    def capture(
        self,
        session: ResolvedSession,
        *,
        frames: int = 160,
        fps: int = 30,
        scale: float = 1.0,
        pivot: tuple[float, float, float] = _DEFAULT_PIVOT,
        distance: float | None = None,
        preset_path: Path | None = None,
    ) -> dict[str, str]:
        _validate_frames(frames)
        _validate_fps(fps)
        _validate_scale(scale)
        normalized_pivot = _validate_pivot(pivot)
        normalized_distance = _validate_distance(distance)
        preset = (
            load_screenshot_preset(preset_path, mode="turntable")
            if preset_path is not None
            else ScreenshotPreset()
        )

        workspace = self._workspaces.allocate(prefix="capture-turntable")
        try:
            frames_dir = workspace.path_for("frames")
            frames_dir.mkdir()
            result_path = workspace.path_for("result.json")
            request_path = workspace.path_for("request.json")
            request_path.write_text(
                json.dumps(
                    {
                        "frames": frames,
                        "frames_dir": str(frames_dir),
                        "result_path": str(result_path),
                        "scale": scale,
                        "pivot": list(normalized_pivot),
                        "distance": normalized_distance,
                        "max_width": self._config.max_width,
                        "max_height": self._config.max_height,
                        "preset": preset.to_dict(),
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
                filename="turntable.py",
            )
            self._transport.execute_script(session.target, runner)
            _require_turntable_success(result_path)
            _validate_captured_frames(
                frames_dir,
                frames=frames,
                max_width=self._config.max_width,
                max_height=self._config.max_height,
            )

            video_path = workspace.path_for("turntable.mp4")
            encode_turntable_ffmpeg(frames_dir, fps=fps, output_path=video_path)
            if not video_path.is_file():
                raise BridgeError(
                    "ffmpeg_encode_failed",
                    "ffmpeg returned without producing the turntable video.",
                )

            self._publisher.cleanup_expired()
            published = self._publisher.publish_turntable_mp4(video_path)
            return {"path": str(published)}
        except BridgeError:
            raise
        except (OSError, ValueError) as exc:
            raise BridgeError(
                "turntable_failed",
                "Turntable capture failed.",
                f"{type(exc).__name__}: {exc}",
            ) from exc
        finally:
            workspace.remove()


def parse_turntable_pivot(value: str) -> tuple[float, float, float]:
    parts = [part.strip() for part in value.split(",")]
    if len(parts) != 3:
        raise BridgeError(
            "invalid_turntable_pivot",
            "Turntable pivot must be three finite comma-separated coordinates: x,y,z.",
        )
    try:
        x, y, z = (float(part) for part in parts)
        pivot = (x, y, z)
    except ValueError as exc:
        raise BridgeError(
            "invalid_turntable_pivot",
            "Turntable pivot must be three finite comma-separated coordinates: x,y,z.",
        ) from exc
    return _validate_pivot(pivot)


def _validate_pivot(value: tuple[float, float, float]) -> tuple[float, float, float]:
    if len(value) != 3 or not all(
        not isinstance(component, bool)
        and isinstance(component, (int, float))
        and math.isfinite(float(component))
        for component in value
    ):
        raise BridgeError(
            "invalid_turntable_pivot",
            "Turntable pivot must be three finite comma-separated coordinates: x,y,z.",
        )
    x, y, z = (float(component) for component in value)
    return x, y, z


def _validate_distance(value: float | None) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise BridgeError(
            "invalid_turntable_distance",
            "Turntable distance must be a finite number greater than zero.",
        )
    distance = float(value)
    if not math.isfinite(distance) or distance <= 0:
        raise BridgeError(
            "invalid_turntable_distance",
            "Turntable distance must be a finite number greater than zero.",
        )
    return distance


def _validate_frames(value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 2:
        raise BridgeError("invalid_turntable_frames", "Turntable frames must be >= 2.")


def _validate_fps(value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise BridgeError("invalid_turntable_fps", "Turntable fps must be >= 1.")


def _validate_scale(value: float) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise BridgeError(
            "invalid_screenshot_scale",
            "Screenshot scale must be greater than zero.",
        )
    scale = float(value)
    if not math.isfinite(scale) or scale <= 0:
        raise BridgeError(
            "invalid_screenshot_scale",
            "Screenshot scale must be greater than zero.",
        )


def _validate_captured_frames(
    frames_dir: Path,
    *,
    frames: int,
    max_width: int,
    max_height: int,
) -> None:
    expected = tuple(
        frames_dir / f"frame{index:04d}.png"
        for index in range(1, frames + 1)
    )
    if not all(path.is_file() for path in expected):
        found = len(tuple(frames_dir.glob("frame[0-9][0-9][0-9][0-9].png")))
        raise BridgeError(
            "turntable_frames_missing",
            f"Expected {frames} turntable frames but found {found}.",
        )
    for path in expected:
        width, height = png_size(path)
        if width > max_width or height > max_height:
            raise BridgeError(
                "screenshot_size_limit_failed",
                "Turntable frame exceeded the configured maximum dimensions.",
            )


def _require_turntable_success(path: Path) -> None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise BridgeError(
            "turntable_failed",
            "Houdini returned without writing turntable status.",
        ) from exc
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise BridgeError(
            "turntable_failed",
            "Turntable status is unreadable or invalid JSON.",
            f"{type(exc).__name__}: {exc}",
        ) from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("ok"), bool):
        raise BridgeError("turntable_failed", "Turntable status has an invalid shape.")
    if payload["ok"]:
        return
    message = payload.get("message")
    detail = payload.get("detail")
    raise BridgeError(
        "turntable_failed",
        message if isinstance(message, str) and message else "Turntable capture failed inside Houdini.",
        detail if isinstance(detail, str) and detail else None,
    )
