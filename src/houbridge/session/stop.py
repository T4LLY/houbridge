from __future__ import annotations

import json
import time
from collections.abc import Callable
from pathlib import Path

from houbridge.errors import BridgeError
from houbridge.houdini.transport import HoudiniTransport
from houbridge.process_coordination import ProcessIdentity, process_identity_for_pid
from houbridge.temporary_workspace import TemporaryWorkspaceService

from .registry import SessionRecord, SessionRegistry, SessionRegistryState
from .resolver import SessionResolver


class SessionStopService:
    """Gracefully stop one live Houdini Session without implicitly saving it."""

    def __init__(
        self,
        registry: SessionRegistry,
        resolver: SessionResolver,
        transport: HoudiniTransport,
        *,
        shutdown_timeout_seconds: float,
        poll_interval_seconds: float,
        identity_reader: Callable[[int], ProcessIdentity] = process_identity_for_pid,
        workspaces: TemporaryWorkspaceService | None = None,
        script_path: Path | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._registry = registry
        self._resolver = resolver
        self._transport = transport
        self._shutdown_timeout_seconds = shutdown_timeout_seconds
        self._poll_interval_seconds = poll_interval_seconds
        self._identity_reader = identity_reader
        self._workspaces = workspaces or TemporaryWorkspaceService()
        self._monotonic = monotonic
        self._sleep = sleep
        if script_path is None:
            from houbridge.houdini.scripts.session import stop

            script_path = Path(stop.__file__)
        self._script_path = script_path.resolve()

    def stop(self, session: int) -> dict[str, int]:
        _require_positive_session(session)
        resolved = self._resolver.resolve(session)
        record = resolved.record

        self._request_stop(resolved.target)
        self._wait_for_exit(record)
        self._remove_record_if_unchanged(record)
        return {"stopped": session}

    def _request_stop(self, target) -> None:
        workspace = self._workspaces.allocate(prefix="session-stop")
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
            runner = workspace.path_for("session-stop.py")
            runner.write_text(
                "from __future__ import annotations\n"
                "import runpy\n"
                f"_runtime = runpy.run_path("
                f"{json.dumps(str(self._script_path), ensure_ascii=False)})\n"
                f"_runtime['run']({json.dumps(str(request_path), ensure_ascii=False)})\n",
                encoding="utf-8",
                newline="\n",
            )

            try:
                self._transport.execute_script(target, runner)
            except BridgeError:
                # A clean exit can close the openport while hcommand unwinds.
                # The in-process result marker plus PID confirmation below decide success.
                pass

            payload = _read_result(result_path)
            if payload["ok"] is False:
                raise BridgeError(
                    str(payload["code"]),
                    str(payload["message"]),
                    str(payload["detail"]) if payload.get("detail") else None,
                )
            if payload.get("status") != "stopping":
                raise BridgeError(
                    "session_stop_failed",
                    "Houdini returned an invalid graceful-stop status.",
                )

        finally:
            workspace.remove()

    def _wait_for_exit(self, record: SessionRecord) -> None:
        deadline = self._monotonic() + self._shutdown_timeout_seconds
        while True:
            try:
                identity = self._identity_reader(record.pid)
            except ProcessLookupError:
                return
            except (PermissionError, OSError):
                identity = None

            if identity is not None:
                if identity.pid != record.pid:
                    return
                if (
                    record.process_start_identity is not None
                    and identity.process_start_identity != record.process_start_identity
                ):
                    return

            if self._monotonic() >= deadline:
                raise BridgeError(
                    "session_stop_timeout",
                    (
                        f"Houdini session {record.session} did not exit before "
                        "the graceful-stop timeout."
                    ),
                    f"pid={record.pid}",
                )
            self._sleep(self._poll_interval_seconds)

    def _remove_record_if_unchanged(self, record: SessionRecord) -> None:
        with self._registry.locked():
            state = self._registry.load()
            if state.sessions.get(record.session) != record:
                return
            sessions = dict(state.sessions)
            del sessions[record.session]
            primary = None if state.primary == record.session else state.primary
            self._registry.save(SessionRegistryState(primary=primary, sessions=sessions))


def _read_result(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise BridgeError(
            "session_stop_failed",
            "Houdini returned without publishing graceful-stop status.",
        ) from exc
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise BridgeError(
            "session_stop_failed",
            "Houdini graceful-stop status is unreadable or invalid JSON.",
            f"{type(exc).__name__}: {exc}",
        ) from exc

    if not isinstance(payload, dict) or not isinstance(payload.get("ok"), bool):
        raise BridgeError(
            "session_stop_failed",
            "Houdini graceful-stop status has an invalid shape.",
        )
    if payload["ok"] is False:
        code = payload.get("code")
        message = payload.get("message")
        detail = payload.get("detail")
        if not isinstance(code, str) or not code:
            code = "session_stop_failed"
        if not isinstance(message, str) or not message:
            message = "Houdini graceful stop failed."
        if not isinstance(detail, str) or not detail:
            detail = None
        return {"ok": False, "code": code, "message": message, "detail": detail}

    if set(payload) != {"ok", "status", "path"}:
        raise BridgeError(
            "session_stop_failed",
            "Houdini graceful-stop status has unexpected fields.",
        )
    status = payload.get("status")
    hip_path = payload.get("path")
    if status != "stopping" or not isinstance(hip_path, str) or not hip_path:
        raise BridgeError(
            "session_stop_failed",
            "Houdini graceful-stop status contains invalid fields.",
        )
    return {"ok": True, "status": status, "path": hip_path}


def _require_positive_session(value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise BridgeError("invalid_session", "SESSION must be a positive integer.")
