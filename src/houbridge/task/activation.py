from __future__ import annotations

import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from houbridge.errors import BridgeError

from .runtime_store import TaskRuntimeStateStore


@dataclass(slots=True)
class TaskRuntimeProcessLauncher:
    """Launch one detached on-demand Task Runtime and verify ownership handoff."""

    runtime_state: TaskRuntimeStateStore
    tasks_database: Path
    resources_database: Path
    resource_ttl_hours: int
    max_concurrency: int
    handoff_timeout_seconds: float
    lock_timeout_seconds: float
    poll_interval_seconds: float = 0.05
    popen: Callable[..., subprocess.Popen[bytes]] = subprocess.Popen
    monotonic: Callable[[], float] = time.monotonic
    sleep: Callable[[float], None] = time.sleep

    def __post_init__(self) -> None:
        if self.handoff_timeout_seconds <= 0:
            raise ValueError("handoff_timeout_seconds must be > 0")
        if self.lock_timeout_seconds <= 0:
            raise ValueError("lock_timeout_seconds must be > 0")
        if self.poll_interval_seconds <= 0:
            raise ValueError("poll_interval_seconds must be > 0")

    def __call__(self, owner_token: str) -> None:
        args = [
            sys.executable,
            "-m",
            "houbridge.task.worker",
            "--owner-token",
            owner_token,
            "--tasks-db",
            str(self.tasks_database),
            "--resources-db",
            str(self.resources_database),
            "--resource-ttl-hours",
            str(self.resource_ttl_hours),
            "--max-concurrency",
            str(self.max_concurrency),
            "--lock-timeout-seconds",
            str(self.lock_timeout_seconds),
        ]
        kwargs: dict[str, object] = {
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
            "close_fds": True,
        }
        if os.name == "nt":
            creationflags = 0
            creationflags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            creationflags |= getattr(subprocess, "DETACHED_PROCESS", 0)
            kwargs["creationflags"] = creationflags
        else:
            kwargs["start_new_session"] = True

        try:
            process = self.popen(args, **kwargs)
        except OSError as exc:
            raise BridgeError(
                "task_runtime_handoff_failed",
                "Task Runtime process could not be started.",
                f"{type(exc).__name__}: {exc}",
            ) from exc

        deadline = self.monotonic() + self.handoff_timeout_seconds
        while True:
            owner = self.runtime_state.runtime_owner()
            if (
                owner is not None
                and owner.token == owner_token
                and owner.runtime_identity is not None
            ):
                return

            returncode = process.poll()
            if returncode is not None:
                raise BridgeError(
                    "task_runtime_handoff_failed",
                    "Task Runtime exited before ownership handoff completed.",
                    f"status={returncode}",
                )
            if self.monotonic() >= deadline:
                _terminate(process)
                raise BridgeError(
                    "task_runtime_handoff_timeout",
                    "Task Runtime ownership handoff timed out.",
                )
            self.sleep(self.poll_interval_seconds)


def _terminate(process: subprocess.Popen[bytes]) -> None:
    try:
        if process.poll() is None:
            process.terminate()
    except OSError:
        pass
