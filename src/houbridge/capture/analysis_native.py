from __future__ import annotations

import json
from pathlib import Path

from houbridge.errors import BridgeError
from houbridge.houdini.transport import HoudiniTransport
from houbridge.session.resolver import ResolvedSession
from houbridge.temporary_workspace import TemporaryWorkspace

from ._injected import write_runpy_runner
from .analysis import AnalysisCaptureRequest, CameraAnalysisSource, ViewportAnalysisSource
from .native import NativeCaptureBuilder


class NativeAnalysisCaptureBackend:
    """Render non-beauty Capture passes through the cached native SceneHook."""

    def __init__(
        self,
        transport: HoudiniTransport,
        builder: NativeCaptureBuilder,
        *,
        viewport_script_path: Path | None = None,
        camera_script_path: Path | None = None,
    ) -> None:
        self._transport = transport
        self._builder = builder
        if viewport_script_path is None:
            from houbridge.houdini.scripts.capture import analysis_viewport

            viewport_script_path = Path(analysis_viewport.__file__)
        if camera_script_path is None:
            from houbridge.houdini.scripts.capture import analysis_camera

            camera_script_path = Path(analysis_camera.__file__)
        self._viewport_script_path = viewport_script_path.resolve()
        self._camera_script_path = camera_script_path.resolve()

    def render_viewport(
        self,
        session: ResolvedSession,
        request: AnalysisCaptureRequest,
        source: ViewportAnalysisSource,
        workspace: TemporaryWorkspace,
    ) -> None:
        if request.capture_pass not in {"depth", "grid", "normal", "object-id", "curvature"}:
            raise BridgeError(
                "capture_analysis_pass_unavailable",
                f"Capture pass {request.capture_pass!r} is not implemented yet.",
            )
        artifact = self._builder.ensure(
            houdini_build=session.probe.version,
            hcommand=self._transport.executable,
            environ=self._transport.subprocess_environment(),
        )
        result_path = workspace.path_for("analysis-result.json")
        request_path = workspace.path_for("analysis-request.json")
        trigger_paths = tuple(
            workspace.path_for(f"analysis-trigger-{index:03d}.png")
            for index in range(len(source.png_paths))
        )
        request_path.write_text(
            json.dumps(
                {
                    "dso_path": str(artifact.path),
                    "generation": artifact.generation,
                    "analysis": request.to_dict(),
                    "png_paths": [str(path) for path in source.png_paths],
                    "trigger_paths": [str(path) for path in trigger_paths],
                    "requested_views": list(source.requested_views),
                    "scale": source.scale,
                    "max_width": source.max_width,
                    "max_height": source.max_height,
                    "pane": source.pane,
                    "result_path": str(result_path),
                },
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            encoding="utf-8",
            newline="\n",
        )
        runner = write_runpy_runner(
            workspace,
            script_path=self._viewport_script_path,
            request_path=request_path,
            filename="analysis_viewport.py",
        )
        self._transport.execute_script(session.target, runner)
        _require_analysis_success(result_path)

    def render_camera(
        self,
        session: ResolvedSession,
        request: AnalysisCaptureRequest,
        source: CameraAnalysisSource,
        workspace: TemporaryWorkspace,
    ) -> None:
        if request.capture_pass not in {"depth", "grid", "normal", "object-id", "curvature"}:
            raise BridgeError(
                "capture_analysis_pass_unavailable",
                f"Capture pass {request.capture_pass!r} is not implemented yet.",
            )
        artifact = self._builder.ensure(
            houdini_build=session.probe.version,
            hcommand=self._transport.executable,
            environ=self._transport.subprocess_environment(),
        )
        result_path = workspace.path_for("analysis-result.json")
        request_path = workspace.path_for("analysis-request.json")
        trigger_path = workspace.path_for("analysis-trigger.png")
        request_path.write_text(
            json.dumps(
                {
                    "dso_path": str(artifact.path),
                    "generation": artifact.generation,
                    "analysis": request.to_dict(),
                    "png_path": str(source.png_path),
                    "trigger_path": str(trigger_path),
                    "camera_path": source.camera_path,
                    "scale": source.scale,
                    "max_width": source.max_width,
                    "max_height": source.max_height,
                    "pane": source.pane,
                    "result_path": str(result_path),
                },
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            encoding="utf-8",
            newline="\n",
        )
        runner = write_runpy_runner(
            workspace,
            script_path=self._camera_script_path,
            request_path=request_path,
            filename="analysis_camera.py",
        )
        self._transport.execute_script(session.target, runner)
        _require_analysis_success(result_path)


def _require_analysis_success(path: Path) -> None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise BridgeError(
            "capture_analysis_failed",
            "Houdini returned without publishing analysis capture status.",
        ) from exc
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise BridgeError(
            "capture_analysis_failed",
            "Analysis capture status is unreadable or invalid JSON.",
            f"{type(exc).__name__}: {exc}",
        ) from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("ok"), bool):
        raise BridgeError("capture_analysis_failed", "Analysis capture status has an invalid shape.")
    if payload["ok"]:
        return
    code = payload.get("code")
    message = payload.get("message")
    detail = payload.get("detail")
    context = payload.get("context")
    if not isinstance(code, str) or not code:
        code = "capture_analysis_failed"
    if not isinstance(message, str) or not message:
        message = "Analysis capture failed inside Houdini."
    if detail is not None and not isinstance(detail, str):
        detail = None
    if context is not None and not isinstance(context, dict):
        context = None
    raise BridgeError(code, message, detail, context=context)
