from __future__ import annotations

import json
from pathlib import Path

from houbridge.errors import BridgeError
from houbridge.houdini.transport import HoudiniTransport
from houbridge.session.resolver import ResolvedSession
from houbridge.temporary_workspace import TemporaryWorkspaceService

from ._injected import write_runpy_runner


class ViewportInfoService:
    def __init__(
        self,
        transport: HoudiniTransport,
        *,
        workspaces: TemporaryWorkspaceService | None = None,
        script_path: Path | None = None,
    ) -> None:
        self._transport = transport
        self._workspaces = workspaces or TemporaryWorkspaceService()
        if script_path is None:
            from houbridge.houdini.scripts.capture import viewport_info

            script_path = Path(viewport_info.__file__)
        self._script_path = script_path.resolve()

    def info(self, session: ResolvedSession) -> dict[str, object]:
        workspace = self._workspaces.allocate(prefix="capture-viewport-info")
        try:
            result_path = workspace.path_for("result.json")
            request_path = workspace.path_for("request.json")
            request_path.write_text(
                json.dumps(
                    {"output_path": str(result_path)},
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                encoding="utf-8",
            )
            runner = write_runpy_runner(
                workspace,
                script_path=self._script_path,
                request_path=request_path,
                filename="viewport-info.py",
            )
            self._transport.execute_script(session.target, runner)
            return _read_viewport_info(result_path)
        finally:
            workspace.remove()


def _read_viewport_info(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise BridgeError(
            "viewport_info_missing",
            "Houdini returned without writing viewport information.",
        ) from exc
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise BridgeError(
            "viewport_info_invalid",
            "Houdini viewport information is unreadable or invalid JSON.",
            f"{type(exc).__name__}: {exc}",
        ) from exc
    if not isinstance(payload, dict):
        raise BridgeError(
            "viewport_info_invalid",
            "Houdini viewport information is not a JSON object.",
        )
    if payload.get("ok") is False:
        raise BridgeError(
            "viewport_unavailable",
            str(payload.get("message") or "No Scene Viewer pane is available."),
        )
    if set(payload) != {"ok", "viewports"} or payload.get("ok") is not True:
        raise BridgeError(
            "viewport_info_invalid",
            "Houdini viewport information has an invalid result envelope.",
        )
    viewports = payload.get("viewports")
    if not isinstance(viewports, list):
        raise BridgeError(
            "viewport_info_invalid",
            "Houdini viewport information has no viewports array.",
        )
    normalized: list[dict[str, object]] = []
    for item in viewports:
        if not isinstance(item, dict) or set(item) != {"name", "type", "width", "height"}:
            raise BridgeError(
                "viewport_info_invalid",
                "Houdini viewport entry is invalid.",
            )
        name = item.get("name")
        viewport_type = item.get("type")
        width = item.get("width")
        height = item.get("height")
        if (
            not isinstance(name, str)
            or not isinstance(viewport_type, str)
            or isinstance(width, bool)
            or not isinstance(width, int)
            or isinstance(height, bool)
            or not isinstance(height, int)
            or width < 0
            or height < 0
        ):
            raise BridgeError(
                "viewport_info_invalid",
                "Houdini viewport entry has invalid fields.",
            )
        normalized.append(
            {"name": name, "type": viewport_type, "width": width, "height": height}
        )
    return {"viewports": normalized}
