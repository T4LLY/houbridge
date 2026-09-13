from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from houbridge.errors import BridgeError
from houbridge.houdini.transport import HoudiniTarget, HoudiniTransport
from houbridge.temporary_workspace import TemporaryWorkspaceService

from .diagnostics import append_diagnostic_path, write_failure, write_text


@dataclass(frozen=True, slots=True)
class SessionProbeResult:
    pid: int
    version: str
    license: str
    file: str | None
    headless: bool
    open_ports: tuple[int, ...]


class SessionProbe:
    """Run the physical Session probe script inside the selected Houdini process."""

    def __init__(
        self,
        transport_factory: Callable[[], HoudiniTransport],
        *,
        workspaces: TemporaryWorkspaceService | None = None,
        probe_script: Path | None = None,
    ) -> None:
        self._transport_factory = transport_factory
        self._workspaces = workspaces or TemporaryWorkspaceService()
        self._probe_script = probe_script or (
            Path(__file__).parents[1] / "houdini" / "scripts" / "session" / "probe.py"
        )

    def inspect(self, port: int) -> SessionProbeResult:
        workspace = self._workspaces.allocate(prefix="session-probe")
        failed = False
        try:
            script_path = workspace.path_for("session_probe.py")
            try:
                shutil.copyfile(self._probe_script, script_path)
            except OSError as exc:
                raise BridgeError(
                    "session_probe_unavailable",
                    "Unable to prepare the Houdini Session probe.",
                    f"{type(exc).__name__}: {exc}",
                ) from exc

            result_path = script_path.with_suffix(".json")
            workspace.publish_marker(
                "probe.context.json",
                json.dumps(
                    {"host": "127.0.0.1", "port": port},
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode("utf-8"),
            )
            transport_result = self._transport_factory().execute_script(
                HoudiniTarget(host="127.0.0.1", port=port),
                script_path,
            )
            if transport_result is not None:
                write_text(workspace.directory, "hcommand.stdout.log", transport_result.stdout)
                write_text(workspace.directory, "hcommand.stderr.log", transport_result.stderr)
            try:
                raw = json.loads(result_path.read_text(encoding="utf-8"))
            except FileNotFoundError as exc:
                raise BridgeError(
                    "session_probe_missing",
                    "Houdini did not publish the Session probe result.",
                ) from exc
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise BridgeError(
                    "session_probe_invalid",
                    "Houdini Session probe returned invalid JSON.",
                    f"{type(exc).__name__}: {exc}",
                ) from exc
            return _parse_probe_result(raw)
        except BaseException as exc:
            failed = True
            write_failure(workspace.directory, "probe.error.txt", exc)
            if isinstance(exc, BridgeError):
                raise BridgeError(
                    exc.code,
                    exc.message,
                    append_diagnostic_path(
                        exc.detail,
                        workspace.directory,
                        label="probe_diagnostics",
                    ),
                ) from exc
            raise
        finally:
            if not failed:
                workspace.remove()


def _parse_probe_result(raw: object) -> SessionProbeResult:
    if not isinstance(raw, dict):
        raise BridgeError("session_probe_invalid", "Session probe payload is not an object.")
    if set(raw) != {"pid", "version", "license", "file", "headless", "open_ports"}:
        raise BridgeError(
            "session_probe_invalid",
            "Session probe payload has unexpected fields.",
        )

    pid = raw["pid"]
    version = raw["version"]
    license_name = raw["license"]
    file_name = raw["file"]
    headless = raw["headless"]
    ports = raw["open_ports"]

    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
        raise BridgeError("session_probe_invalid", "Session probe PID is invalid.")
    if not isinstance(version, str) or not version:
        raise BridgeError("session_probe_invalid", "Session probe version is invalid.")
    if not isinstance(license_name, str) or not license_name:
        raise BridgeError("session_probe_invalid", "Session probe license is invalid.")
    if file_name is not None and not isinstance(file_name, str):
        raise BridgeError("session_probe_invalid", "Session probe file is invalid.")
    if not isinstance(headless, bool):
        raise BridgeError("session_probe_invalid", "Session probe headless flag is invalid.")
    if not isinstance(ports, list):
        raise BridgeError("session_probe_invalid", "Session probe open_ports is invalid.")

    normalized_ports: list[int] = []
    for port in ports:
        if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
            raise BridgeError("session_probe_invalid", "Session probe contains an invalid port.")
        normalized_ports.append(port)

    return SessionProbeResult(
        pid=pid,
        version=version,
        license=license_name,
        file=file_name if file_name else None,
        headless=headless,
        open_ports=tuple(normalized_ports),
    )
