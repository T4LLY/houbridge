from __future__ import annotations

import json
import os
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Protocol

from houbridge.config import HoudiniConfig
from houbridge.errors import BridgeError
from houbridge.houdini.installations import (
    resolve_session_launch_executable,
    subprocess_environment_for,
)
from houbridge.process_coordination import ProcessIdentity, process_identity_for_pid
from houbridge.temporary_workspace import TemporaryWorkspaceService

from .diagnostics import append_diagnostic_path, write_failure
from .probe import SessionProbe, SessionProbeResult


class _Process(Protocol):
    pid: int

    def poll(self) -> int | None: ...

    def terminate(self) -> None: ...

    def kill(self) -> None: ...

    def wait(self, timeout: float | None = None) -> int: ...


@dataclass(frozen=True, slots=True)
class SessionLaunchResult:
    pid: int
    port: int
    identity: ProcessIdentity
    probe: SessionProbeResult
    process: _Process


class HoudiniSessionLauncher:
    """Launch exactly one new Houdini process and complete Session bootstrap."""

    def __init__(
        self,
        config: HoudiniConfig,
        probe_factory: Callable[[Path], SessionProbe],
        *,
        workspaces: TemporaryWorkspaceService | None = None,
        bootstrap_script: Path | None = None,
        headless_notifier_script: Path | None = None,
        headless_rebind_script: Path | None = None,
        python_executable: Path | None = None,
        popen: Callable[..., _Process] = subprocess.Popen,  # type: ignore[assignment]
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        identity_reader: Callable[[int], ProcessIdentity] = process_identity_for_pid,
        executable_resolver: Callable[..., Path] = resolve_session_launch_executable,
        port_ready: Callable[[int], bool] | None = None,
        environ: Mapping[str, str] | None = None,
        platform: str | None = None,
    ) -> None:
        self._config = config
        self._probe_factory = probe_factory
        self._workspaces = workspaces or TemporaryWorkspaceService()
        session_scripts = Path(__file__).parents[1] / "houdini" / "scripts" / "session"
        self._bootstrap_script = bootstrap_script or (session_scripts / "bootstrap.py")
        self._headless_notifier_script = headless_notifier_script or (
            session_scripts / "headless_port_notifier.py"
        )
        self._headless_rebind_script = headless_rebind_script or (
            session_scripts / "headless_rebind.py"
        )
        self._python_executable = python_executable or Path(sys.executable)
        self._popen = popen
        self._monotonic = monotonic
        self._sleep = sleep
        self._identity_reader = identity_reader
        self._executable_resolver = executable_resolver
        self._port_ready = port_ready or _local_port_accepting
        self._environ = os.environ if environ is None else environ
        self._platform = sys.platform if platform is None else platform

    def launch(
        self,
        *,
        hip_file: Path | None = None,
        headless: bool = False,
        hcommand: Path | None = None,
    ) -> SessionLaunchResult:
        requested_file = _validate_hip_file(hip_file)
        executable = self._executable_resolver(
            hcommand,
            self._config.hcommand,
            headless=headless,
            environ=self._environ,
            platform=self._platform,
        )
        workspace = self._workspaces.allocate(prefix="session-new")
        process: _Process | None = None
        bootstrap_pid: int | None = None
        failed = False
        try:
            request = {
                "file": str(requested_file) if requested_file is not None else None,
                "headless": bool(headless),
            }
            workspace.publish_marker(
                "bootstrap.request.json",
                json.dumps(request, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
            )
            result_path = workspace.path_for("bootstrap.result.json")
            rebind_marker = workspace.path_for("bootstrap.rebind.ready")

            if headless:
                notifier_path = workspace.path_for("headless_port_notifier.py")
                rebind_path = workspace.path_for("headless_rebind.py")
                self._copy_bootstrap_script(self._headless_notifier_script, notifier_path)
                self._copy_bootstrap_script(self._headless_rebind_script, rebind_path)
                args = [str(executable)]
                if requested_file is not None:
                    args.append(str(requested_file))
            else:
                script_path = workspace.path_for("bootstrap.py")
                self._copy_bootstrap_script(self._bootstrap_script, script_path)
                args = [str(executable), str(script_path)]
                notifier_path = None
                rebind_path = None

            launch_env = subprocess_environment_for(executable, environ=self._environ)
            launch_env["HOUBRIDGE_SESSION_BOOTSTRAP_DIR"] = str(workspace.directory)
            workspace.publish_marker(
                "launch.context.json",
                json.dumps(
                    {
                        "executable": str(executable),
                        "headless": bool(headless),
                        "file": str(requested_file) if requested_file is not None else None,
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode("utf-8"),
            )
            kwargs: dict[str, object] = {
                "env": launch_env,
                "stdin": subprocess.PIPE if headless else subprocess.DEVNULL,
                "stdout": subprocess.DEVNULL,
                "stderr": subprocess.DEVNULL,
            }
            if headless:
                kwargs.update(text=True, encoding="utf-8", errors="replace")
            if executable.parent.name.casefold() == "bin":
                kwargs["cwd"] = str(executable.parent.parent)
            if self._platform.startswith("win"):
                creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                if headless:
                    creationflags |= getattr(subprocess, "CREATE_NO_WINDOW", 0)
                kwargs["creationflags"] = creationflags
            else:
                kwargs["start_new_session"] = True

            try:
                process = self._popen(args, **kwargs)
            except OSError as exc:
                raise BridgeError(
                    "houdini_launch_failed",
                    "Failed to launch Houdini.",
                    f"{type(exc).__name__}: {exc}",
                ) from exc

            if headless:
                assert notifier_path is not None
                wrapper_path = self._write_headless_notifier_wrapper(
                    workspace,
                    notifier_path,
                    process.pid,
                )
                self._write_headless_input(
                    process,
                    f"openport -a -q -r {_hscript_quote_path(wrapper_path)} -p\n",
                    close=False,
                )

            probe = self._probe_factory(executable)
            deadline = self._monotonic() + self._config.startup_timeout_seconds
            last_state: dict[str, object] | None = None
            headless_rebind_queued = False
            while self._monotonic() < deadline:
                state = _read_bootstrap_state(result_path)
                if state is not None:
                    last_state = state
                    bootstrap_pid = _state_pid(state)
                    error = state.get("error")
                    if error is not None:
                        if not isinstance(error, str):
                            error = repr(error)
                        raise BridgeError(
                            "houdini_bootstrap_failed",
                            "Houdini Session bootstrap failed.",
                            error,
                        )
                    port = _state_port(state)
                    if port is not None:
                        if headless:
                            assert rebind_path is not None
                            if not headless_rebind_queued:
                                self._write_headless_input(
                                    process,
                                    (
                                        f"python {_hscript_quote_path(rebind_path)}\n"
                                        f"openport -q -w {port}\n"
                                        "quit -f\n"
                                    ),
                                    close=True,
                                )
                                headless_rebind_queued = True
                            if not rebind_marker.is_file() or not self._port_ready(port):
                                self._sleep(self._config.startup_poll_interval_seconds)
                                continue

                        probe_result = probe.inspect(port)
                        _validate_probe(
                            probe_result,
                            pid=bootstrap_pid,
                            port=port,
                            headless=headless,
                            requested_file=requested_file,
                        )
                        try:
                            identity = self._identity_reader(bootstrap_pid)
                        except (ProcessLookupError, PermissionError, OSError) as exc:
                            raise BridgeError(
                                "session_process_identity_unavailable",
                                "Unable to identify the launched Houdini process incarnation.",
                                f"{type(exc).__name__}: {exc}",
                            ) from exc
                        if identity.pid != bootstrap_pid:
                            raise BridgeError(
                                "session_process_identity_unavailable",
                                "Process identity reader returned a different Houdini PID.",
                            )
                        return SessionLaunchResult(
                            pid=bootstrap_pid,
                            port=port,
                            identity=identity,
                            probe=probe_result,
                            process=process,
                        )

                return_code = process.poll()
                if return_code is not None and (headless or return_code != 0):
                    raise BridgeError(
                        "houdini_launch_failed",
                        f"Houdini exited before Session bootstrap completed (status {return_code}).",
                    )
                self._sleep(self._config.startup_poll_interval_seconds)

            detail = None
            if last_state is not None and last_state.get("pid") is not None:
                detail = f"bootstrap pid={last_state.get('pid')}"
            raise BridgeError(
                "houdini_startup_timeout",
                "Houdini was launched but automatic openport bootstrap did not become usable before the configured timeout.",
                detail,
            )
        except BaseException as exc:
            failed = True
            if process is not None:
                self._terminate(process, bootstrap_pid)
            write_failure(workspace.directory, "launch.error.txt", exc)
            if isinstance(exc, BridgeError):
                raise BridgeError(
                    exc.code,
                    exc.message,
                    append_diagnostic_path(
                        exc.detail,
                        workspace.directory,
                        label="launch_diagnostics",
                    ),
                ) from exc
            raise
        finally:
            if not failed:
                workspace.remove()

    @staticmethod
    def _copy_bootstrap_script(source: Path, destination: Path) -> None:
        try:
            shutil.copyfile(source, destination)
        except OSError as exc:
            raise BridgeError(
                "session_bootstrap_unavailable",
                "Unable to prepare the Houdini Session bootstrap script.",
                f"{type(exc).__name__}: {exc}",
            ) from exc

    def _write_headless_notifier_wrapper(
        self,
        workspace,
        notifier_path: Path,
        houdini_pid: int,
    ) -> Path:
        python_executable = str(self._python_executable)
        if self._platform.startswith("win"):
            path = workspace.path_for("headless-port-notifier.cmd")
            command = subprocess.list2cmdline(
                [python_executable, "-I", str(notifier_path), str(houdini_pid)]
            ).replace("%", "%%")
            content = "\r\n".join(
                (
                    "@echo off",
                    "set PYTHONHOME=",
                    "set PYTHONPATH=",
                    "set PYTHONSTARTUP=",
                    "set PYTHONUSERBASE=",
                    command + " %*",
                    "",
                )
            )
        else:
            path = workspace.path_for("headless-port-notifier.sh")
            command = shlex.join(
                [python_executable, "-I", str(notifier_path), str(houdini_pid)]
            )
            content = (
                "#!/bin/sh\n"
                "unset PYTHONHOME PYTHONPATH PYTHONSTARTUP PYTHONUSERBASE\n"
                f"exec {command} \"$@\"\n"
            )
        try:
            path.write_text(content, encoding="utf-8", newline="")
            if not self._platform.startswith("win"):
                path.chmod(0o700)
        except OSError as exc:
            raise BridgeError(
                "session_bootstrap_unavailable",
                "Unable to prepare the headless Session port notifier.",
                f"{type(exc).__name__}: {exc}",
            ) from exc
        return path

    @staticmethod
    def _write_headless_input(process: _Process, text: str, *, close: bool) -> None:
        stream = getattr(process, "stdin", None)
        if stream is None:
            raise BridgeError(
                "session_bootstrap_unavailable",
                "Headless Houdini did not provide the expected HScript input pipe.",
            )
        try:
            stream.write(text)
            stream.flush()
            if close:
                stream.close()
        except (OSError, ValueError) as exc:
            raise BridgeError(
                "houdini_bootstrap_failed",
                "Unable to drive the headless Houdini Session bootstrap.",
                f"{type(exc).__name__}: {exc}",
            ) from exc

    def release(self, result: SessionLaunchResult) -> None:
        """Keep ownership of the Popen handle until the launched process exits."""

        thread = threading.Thread(
            target=self._reap,
            args=(result.process,),
            name=f"houbridge-session-reaper-{result.pid}",
            daemon=True,
        )
        thread.start()

    def terminate(self, result: SessionLaunchResult) -> None:
        self._terminate(result.process, result.pid)

    @staticmethod
    def _reap(process: _Process) -> None:
        try:
            process.wait()
        except OSError:
            pass

    @staticmethod
    def _terminate(process: _Process, bootstrap_pid: int | None) -> None:
        process_pid = getattr(process, "pid", None)
        try:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=2.0)
                except Exception:
                    try:
                        process.kill()
                    except OSError:
                        pass
        except OSError:
            pass

        if bootstrap_pid is not None and bootstrap_pid != process_pid:
            try:
                os.kill(bootstrap_pid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError, OSError):
                pass


def _hscript_quote_path(path: Path) -> str:
    value = path.resolve().as_posix()
    if any(character in value for character in ('"', "\n", "\r")):
        raise BridgeError(
            "session_bootstrap_unavailable",
            "Session bootstrap path cannot be represented safely in HScript.",
            value,
        )
    return f'"{value}"'


def _local_port_accepting(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.1):
            return True
    except OSError:
        return False


def _validate_hip_file(path: Path | None) -> Path | None:
    if path is None:
        return None
    candidate = path.expanduser()
    try:
        resolved = candidate.resolve(strict=True)
        if not resolved.is_file():
            raise OSError("path is not a file")
        with resolved.open("rb"):
            pass
    except OSError as exc:
        raise BridgeError(
            "session_file_unreadable",
            f"Session HIP file is not a readable file: {candidate}",
            f"{type(exc).__name__}: {exc}",
        ) from exc
    return resolved


def _read_bootstrap_state(path: Path) -> dict[str, object] | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise BridgeError(
            "session_bootstrap_invalid",
            "Houdini Session bootstrap returned invalid state.",
            f"{type(exc).__name__}: {exc}",
        ) from exc
    if not isinstance(raw, dict) or not {"pid", "port"}.issubset(raw):
        raise BridgeError(
            "session_bootstrap_invalid",
            "Houdini Session bootstrap returned invalid state.",
        )
    return raw


def _state_pid(state: dict[str, object]) -> int:
    pid = state.get("pid")
    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
        raise BridgeError("session_bootstrap_invalid", "Session bootstrap PID is invalid.")
    return pid


def _state_port(state: dict[str, object]) -> int | None:
    port = state.get("port")
    if port is None:
        return None
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise BridgeError("session_bootstrap_invalid", "Session bootstrap port is invalid.")
    return port


def _validate_probe(
    probe: SessionProbeResult,
    *,
    pid: int,
    port: int,
    headless: bool,
    requested_file: Path | None,
) -> None:
    if probe.pid != pid:
        raise BridgeError(
            "session_bootstrap_invalid",
            "Post-launch Session probe reported a different Houdini PID.",
        )
    if port not in probe.open_ports:
        raise BridgeError(
            "session_bootstrap_invalid",
            "Post-launch Session probe did not report the automatic openport.",
        )
    if probe.headless is not headless:
        raise BridgeError(
            "session_bootstrap_invalid",
            "Post-launch Session probe did not match the requested process mode.",
        )
    if requested_file is not None:
        if probe.file is None or not _same_path(probe.file, requested_file):
            raise BridgeError(
                "session_bootstrap_invalid",
                "Post-launch Session probe did not report the requested HIP file.",
            )


def _same_path(actual: str, expected: Path) -> bool:
    actual_norm = os.path.normcase(os.path.abspath(os.path.normpath(actual)))
    expected_norm = os.path.normcase(os.path.abspath(os.path.normpath(str(expected))))
    return actual_norm == expected_norm
