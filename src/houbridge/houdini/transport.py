from __future__ import annotations

import ipaddress
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from houbridge.config import HoudiniConfig
from houbridge.errors import BridgeError
from houbridge.houdini.installations import (
    HoudiniInstallation,
    resolve_transport_hcommand,
    subprocess_environment_for,
)
from houbridge.subprocesses import hidden_window_creationflags


@dataclass(frozen=True)
class HoudiniTarget:
    host: str
    port: int


@dataclass(frozen=True)
class TransportResult:
    stdout: str
    stderr: str
    returncode: int


@dataclass(slots=True)
class RunningTransportProcess:
    process: subprocess.Popen[bytes]

    def poll(self) -> int | None:
        return self.process.poll()

    def terminate(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()


class HoudiniTransport:
    """Invocation-local hcommand/openport transport for one Houdini target."""

    def __init__(
        self,
        executable: str | Path,
        *,
        timeout_seconds: float,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        self.executable = Path(executable) if isinstance(executable, Path) else executable
        self.timeout_seconds = timeout_seconds
        self._environ = None if environ is None else dict(environ)

    @classmethod
    def from_config(
        cls,
        settings: HoudiniConfig,
        *,
        installation: HoudiniInstallation | None = None,
        environ: Mapping[str, str] | None = None,
        platform: str | None = None,
    ) -> HoudiniTransport:
        """Build transport from transport settings, not the Session launch executable.

        ``settings.hcommand`` is intentionally not used here: OpenSpec assigns that
        field to ``session new`` launch selection, not to post-bootstrap transport.
        """
        executable = resolve_transport_hcommand(
            installation=installation,
            environ=environ,
            platform=platform,
        )
        return cls(
            executable,
            timeout_seconds=settings.transport_timeout_seconds,
            environ=environ,
        )

    def subprocess_environment(self) -> dict[str, str]:
        """Return the exact subprocess environment that would be used now."""

        return subprocess_environment_for(
            self.executable,
            environ=self._environ,
        )

    def execute_script(
        self,
        target: HoudiniTarget,
        script_path: Path,
    ) -> TransportResult:
        _require_local_target(target)
        if not script_path.is_file():
            raise BridgeError(
                "script_not_found",
                f"Execution script does not exist: {script_path}",
            )

        executable = str(self.executable)
        args = _script_args(self.executable, target, script_path)
        try:
            completed = subprocess.run(
                args,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout_seconds,
                env=subprocess_environment_for(
                    self.executable,
                    environ=self._environ,
                ),
                creationflags=hidden_window_creationflags(),
            )
        except FileNotFoundError as exc:
            raise BridgeError(
                "hcommand_not_found",
                f"hcommand executable was not found: {executable}",
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise BridgeError(
                "hcommand_timeout",
                f"hcommand timed out after {self.timeout_seconds:g} seconds.",
                _timeout_detail(exc),
            ) from exc
        except OSError as exc:
            raise BridgeError(
                "hcommand_failed",
                "Failed to start hcommand.",
                f"{type(exc).__name__}: {exc}",
            ) from exc

        result = TransportResult(
            stdout=completed.stdout or "",
            stderr=completed.stderr or "",
            returncode=completed.returncode,
        )
        if completed.returncode != 0:
            detail = _clip((result.stderr or result.stdout).strip())
            raise BridgeError(
                "houdini_transport_failed",
                f"hcommand exited with status {completed.returncode}.",
                detail or None,
            )
        return result

    def start_script(
        self,
        target: HoudiniTarget,
        script_path: Path,
    ) -> RunningTransportProcess:
        """Start hcommand without imposing the synchronous wall-clock timeout.

        Async Task uses its started marker as the dispatch-establishment boundary.
        Once caller Python has started, the hcommand lifetime must not become a
        timeout on the caller's Python runtime.
        """

        _require_local_target(target)
        if not script_path.is_file():
            raise BridgeError(
                "script_not_found",
                f"Execution script does not exist: {script_path}",
            )
        executable = str(self.executable)
        args = _script_args(self.executable, target, script_path)
        try:
            process = subprocess.Popen(
                args,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=subprocess_environment_for(
                    self.executable,
                    environ=self._environ,
                ),
                creationflags=hidden_window_creationflags(),
            )
        except FileNotFoundError as exc:
            raise BridgeError(
                "hcommand_not_found",
                f"hcommand executable was not found: {executable}",
            ) from exc
        except OSError as exc:
            raise BridgeError(
                "hcommand_failed",
                "Failed to start hcommand.",
                f"{type(exc).__name__}: {exc}",
            ) from exc
        return RunningTransportProcess(process)


def _require_local_target(target: HoudiniTarget) -> None:
    host = target.host.strip().lower().rstrip(".")
    if host in {"localhost", "localhost.localdomain"}:
        return

    try:
        if ipaddress.ip_address(host).is_loopback:
            return
    except ValueError:
        pass

    raise BridgeError(
        "remote_target_disabled",
        "Houdini transport accepts loopback targets only.",
    )


def _script_args(executable: str | Path, target: HoudiniTarget, script_path: Path) -> list[str]:
    command = f'python "{_hscript_path(script_path)}"'
    return [str(executable), str(target.port), command]


def _hscript_path(path: Path) -> str:
    value = path.resolve().as_posix()
    return value.replace('"', '\\"')


def _clip(value: str, limit: int = 4096) -> str:
    if len(value) <= limit:
        return value
    return value[:limit] + "…"


def _timeout_detail(exc: subprocess.TimeoutExpired) -> str | None:
    parts: list[str] = []
    stdout = _timeout_text(exc.stdout)
    stderr = _timeout_text(exc.stderr)
    if stdout:
        parts.append(f"stdout: {_clip(stdout.strip())}")
    if stderr:
        parts.append(f"stderr: {_clip(stderr.strip())}")
    return "\n".join(parts) or None


def _timeout_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value
