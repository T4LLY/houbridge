from __future__ import annotations

import json
from pathlib import Path
from typing import Sequence

from houbridge.errors import BridgeError
from houbridge.houdini.transport import HoudiniTransport
from houbridge.session.resolver import ResolvedSession
from houbridge.temporary_workspace import TemporaryWorkspaceService

from .extractors import CodeExtractorSpec, BUILTIN_CODE_EXTRACTORS, extractor_registry_payload
from .models import LiveCodeEntry


class LiveCodeCapture:
    """Capture current Houdini code through the physical Search script boundary."""

    def __init__(
        self,
        transport: HoudiniTransport,
        *,
        workspaces: TemporaryWorkspaceService | None = None,
        extractors: Sequence[CodeExtractorSpec] = BUILTIN_CODE_EXTRACTORS,
        capture_script: Path | None = None,
    ) -> None:
        self._transport = transport
        self._workspaces = workspaces or TemporaryWorkspaceService()
        self._extractors = tuple(extractors)
        if capture_script is None:
            from houbridge.houdini.scripts.search import live_code_capture

            capture_script = Path(live_code_capture.__file__)
        self._capture_script = capture_script.resolve()

    def capture(
        self,
        session: ResolvedSession,
        *,
        path: str | None = None,
        recursive: bool = False,
    ) -> list[LiveCodeEntry]:
        workspace = self._workspaces.allocate(prefix="live-code-capture")
        try:
            request_path = workspace.path_for("request.json")
            result_path = workspace.path_for("result.json")
            request_path.write_text(
                json.dumps(
                    {
                        "extractors": extractor_registry_payload(self._extractors),
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


def _read_capture_result(path: Path) -> list[LiveCodeEntry]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise BridgeError(
            "node_code_capture_missing",
            "Houdini live-code capture returned no result.",
        ) from exc
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise BridgeError(
            "node_code_capture_invalid",
            "Houdini live-code capture result is invalid.",
            f"{type(exc).__name__}: {exc}",
        ) from exc

    if not isinstance(raw, dict) or set(raw) != {"nodes"} or not isinstance(raw["nodes"], list):
        raise BridgeError(
            "node_code_capture_invalid",
            "Houdini live-code capture result is invalid.",
        )

    entries: list[LiveCodeEntry] = []
    for value in raw["nodes"]:
        entries.append(_parse_entry(value))
    return entries


def _parse_entry(value: object) -> LiveCodeEntry:
    expected = {
        "session_id",
        "path",
        "node_type",
        "slot_id",
        "parameter_name",
        "language",
        "source",
    }
    if not isinstance(value, dict) or set(value) != expected:
        raise BridgeError("node_code_capture_invalid", "Live-code capture entry is invalid.")
    session_id = value["session_id"]
    if isinstance(session_id, bool) or not isinstance(session_id, int) or session_id < 0:
        raise BridgeError("node_code_capture_invalid", "Live-code capture session id is invalid.")
    strings: dict[str, str] = {}
    for key in expected - {"session_id"}:
        item = value[key]
        if not isinstance(item, str):
            raise BridgeError("node_code_capture_invalid", f"Live-code capture {key} is invalid.")
        strings[key] = item
    if strings["language"] not in {"python", "vex"} or not strings["source"].strip():
        raise BridgeError("node_code_capture_invalid", "Live-code capture source metadata is invalid.")
    return LiveCodeEntry(session_id=session_id, **strings)
