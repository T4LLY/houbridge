from __future__ import annotations

import json
from pathlib import Path

from houbridge.errors import BridgeError
from houbridge.houdini.transport import HoudiniTransport
from houbridge.session.resolver import ResolvedSession
from houbridge.temporary_workspace import TemporaryWorkspaceService

from .models import LiveNodeEntry


class LiveNodeCapture:
    """Capture the selected current Houdini node metadata without persisting an index."""

    def __init__(
        self,
        transport: HoudiniTransport,
        *,
        workspaces: TemporaryWorkspaceService | None = None,
        capture_script: Path | None = None,
    ) -> None:
        self._transport = transport
        self._workspaces = workspaces or TemporaryWorkspaceService()
        if capture_script is None:
            from houbridge.houdini.scripts.search import live_node_capture

            capture_script = Path(live_node_capture.__file__)
        self._capture_script = capture_script.resolve()

    def capture(
        self,
        session: ResolvedSession,
        *,
        path: str | None = None,
        recursive: bool = False,
    ) -> list[LiveNodeEntry]:
        workspace = self._workspaces.allocate(prefix="live-node-capture")
        try:
            request_path = workspace.path_for("request.json")
            result_path = workspace.path_for("result.json")
            request_path.write_text(
                json.dumps(
                    {
                        "output_path": str(result_path),
                        "path": path,
                        "recursive": recursive,
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                encoding="utf-8",
            )
            runner_path = workspace.path_for("capture.py")
            runner_path.write_text(
                "from __future__ import annotations\n"
                "import runpy\n"
                f"_runtime = runpy.run_path({json.dumps(str(self._capture_script), ensure_ascii=False)})\n"
                f"_runtime['run']({json.dumps(str(request_path), ensure_ascii=False)})\n",
                encoding="utf-8",
                newline="\n",
            )
            self._transport.execute_script(session.target, runner_path)
            return _read_capture_result(result_path)
        finally:
            workspace.remove()


def _read_capture_result(path: Path) -> list[LiveNodeEntry]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise BridgeError(
            "node_search_result_missing",
            "Houdini live node search returned no result.",
        ) from exc
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise BridgeError(
            "node_search_result_invalid",
            "Houdini live node search result is invalid.",
            f"{type(exc).__name__}: {exc}",
        ) from exc

    if not isinstance(raw, dict) or set(raw) != {"nodes"} or not isinstance(raw["nodes"], list):
        raise BridgeError(
            "node_search_result_invalid",
            "Houdini live node search result is invalid.",
        )

    return [_parse_entry(value) for value in raw["nodes"]]


def _parse_entry(value: object) -> LiveNodeEntry:
    expected = {"path", "name", "type", "category"}
    if not isinstance(value, dict) or set(value) != expected:
        raise BridgeError("node_search_result_invalid", "Live node search entry is invalid.")
    parsed: dict[str, str] = {}
    for key in expected:
        item = value[key]
        if not isinstance(item, str):
            raise BridgeError(
                "node_search_result_invalid",
                f"Live node search {key} is invalid.",
            )
        parsed[key] = item
    return LiveNodeEntry(**parsed)
