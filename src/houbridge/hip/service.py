from __future__ import annotations

import json
from pathlib import Path

from houbridge.errors import BridgeError
from houbridge.houdini.transport import HoudiniTransport
from houbridge.session.resolver import ResolvedSession
from houbridge.temporary_workspace import TemporaryWorkspaceService


class HipFileService:
    """Inspect and save the current native Houdini HIP file."""

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
            from houbridge.houdini.scripts.hip import operation

            script_path = Path(operation.__file__)
        self._script_path = script_path.resolve()

    def info(self, session: ResolvedSession) -> dict[str, object]:
        return self._invoke(session, "info")

    def save(self, session: ResolvedSession) -> dict[str, object]:
        return self._invoke(session, "save")

    def _invoke(self, session: ResolvedSession, mode: str) -> dict[str, object]:
        workspace = self._workspaces.allocate(prefix=f"hip-{mode}")
        try:
            result_path = workspace.path_for("result.json")
            request_path = workspace.path_for("request.json")
            request_path.write_text(
                json.dumps(
                    {"mode": mode, "output_path": str(result_path)},
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                encoding="utf-8",
            )
            runner = workspace.path_for("hip-operation.py")
            runner.write_text(
                "from __future__ import annotations\n"
                "import runpy\n"
                f"_runtime = runpy.run_path({json.dumps(str(self._script_path), ensure_ascii=False)})\n"
                f"_runtime['run']({json.dumps(str(request_path), ensure_ascii=False)})\n",
                encoding="utf-8",
                newline="\n",
            )
            self._transport.execute_script(session.target, runner)
            return _read_result(result_path, mode=mode)
        finally:
            workspace.remove()


def _read_result(path: Path, *, mode: str) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise BridgeError(
            "hip_operation_failed",
            "Houdini returned without writing HIP file status.",
        ) from exc
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise BridgeError(
            "hip_operation_failed",
            "HIP file status is unreadable or invalid JSON.",
            f"{type(exc).__name__}: {exc}",
        ) from exc

    if not isinstance(payload, dict) or not isinstance(payload.get("ok"), bool):
        raise BridgeError("hip_operation_failed", "HIP file status has an invalid shape.")
    if payload["ok"] is False:
        code = payload.get("code")
        message = payload.get("message")
        detail = payload.get("detail")
        if not isinstance(code, str) or not code:
            code = "hip_operation_failed"
        if not isinstance(message, str) or not message:
            message = "HIP file operation failed inside Houdini."
        if not isinstance(detail, str) or not detail:
            detail = None
        raise BridgeError(code, message, detail[:4096] if detail else None)

    hip_path = payload.get("path")
    if not isinstance(hip_path, str) or not hip_path:
        raise BridgeError("hip_operation_failed", "HIP file status contains invalid fields.")

    if mode == "save":
        if set(payload) != {"ok", "path", "status"}:
            raise BridgeError("hip_operation_failed", "HIP file status has unexpected fields.")
        status = payload.get("status")
        if not isinstance(status, str) or status not in {"saved", "unchanged"}:
            raise BridgeError("hip_operation_failed", "HIP file status contains invalid fields.")
        return {"path": hip_path, "status": status}

    if set(payload) != {"ok", "path", "dirty", "new"}:
        raise BridgeError("hip_operation_failed", "HIP file status has unexpected fields.")
    dirty = payload.get("dirty")
    is_new = payload.get("new")
    if not isinstance(dirty, bool) or not isinstance(is_new, bool):
        raise BridgeError("hip_operation_failed", "HIP file status contains invalid fields.")
    return {"path": hip_path, "dirty": dirty, "new": is_new}
