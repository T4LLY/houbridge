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


def _normalize_scene_viewer_catalog(catalog: object) -> dict[str, object]:
    if not isinstance(catalog, dict) or set(catalog) != {"panes"}:
        raise BridgeError(
            "viewport_info_invalid",
            "Houdini Scene Viewer catalog is invalid.",
        )
    panes = catalog.get("panes")
    if not isinstance(panes, list):
        raise BridgeError(
            "viewport_info_invalid",
            "Houdini Scene Viewer catalog has no panes array.",
        )

    normalized_panes: list[dict[str, object]] = []
    for pane in panes:
        if not isinstance(pane, dict) or set(pane) != {
            "name",
            "current_node",
            "viewports",
        }:
            raise BridgeError(
                "viewport_info_invalid",
                "Houdini Scene Viewer pane entry is invalid.",
            )
        name = pane.get("name")
        current_node = pane.get("current_node")
        viewports = pane.get("viewports")
        if (
            not isinstance(name, str)
            or (current_node is not None and not isinstance(current_node, str))
            or not isinstance(viewports, list)
        ):
            raise BridgeError(
                "viewport_info_invalid",
                "Houdini Scene Viewer pane entry has invalid fields.",
            )

        normalized_viewports: list[dict[str, object]] = []
        for viewport in viewports:
            if not isinstance(viewport, dict) or set(viewport) != {
                "name",
                "type",
                "width",
                "height",
            }:
                raise BridgeError(
                    "viewport_info_invalid",
                    "Houdini viewport entry is invalid.",
                )
            viewport_name = viewport.get("name")
            viewport_type = viewport.get("type")
            width = viewport.get("width")
            height = viewport.get("height")
            if (
                not isinstance(viewport_name, str)
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
            normalized_viewports.append(
                {
                    "name": viewport_name,
                    "type": viewport_type,
                    "width": width,
                    "height": height,
                }
            )
        normalized_panes.append(
            {
                "name": name,
                "current_node": current_node,
                "viewports": normalized_viewports,
            }
        )
    return {"panes": normalized_panes}


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
    if set(payload) != {"ok", "panes"} or payload.get("ok") is not True:
        raise BridgeError(
            "viewport_info_invalid",
            "Houdini viewport information has an invalid result envelope.",
        )
    return _normalize_scene_viewer_catalog({"panes": payload.get("panes")})
