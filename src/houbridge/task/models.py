from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Literal, Mapping

from houbridge.process_coordination import ProcessIdentity


TaskStatus = Literal["queued", "running", "completed", "failed"]
TASK_STATUSES: tuple[TaskStatus, ...] = ("queued", "running", "completed", "failed")


@dataclass(frozen=True, slots=True)
class FrozenDispatchContext:
    """Submission-time target and transport context owned by Task."""

    session: int
    port: int
    pid: int
    process_start_identity: str
    transport_executable: str
    transport_timeout_seconds: float
    transport_environment: Mapping[str, str]
    lock_timeout_seconds: float

    def __post_init__(self) -> None:
        for value, label in ((self.session, "session"), (self.pid, "pid")):
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{label} must be a positive integer")
        if isinstance(self.port, bool) or not isinstance(self.port, int) or not 1 <= self.port <= 65535:
            raise ValueError("port must be an integer in the range 1..65535")
        identity = self.process_start_identity.strip()
        if not identity:
            raise ValueError("process_start_identity must not be empty")
        executable = self.transport_executable.strip()
        if not executable:
            raise ValueError("transport_executable must not be empty")
        if self.transport_timeout_seconds <= 0:
            raise ValueError("transport_timeout_seconds must be > 0")
        if self.lock_timeout_seconds <= 0:
            raise ValueError("lock_timeout_seconds must be > 0")
        environment = {str(key): str(value) for key, value in self.transport_environment.items()}
        object.__setattr__(self, "process_start_identity", identity)
        object.__setattr__(self, "transport_executable", executable)
        object.__setattr__(self, "transport_environment", MappingProxyType(environment))

    @property
    def process_identity(self) -> ProcessIdentity:
        return ProcessIdentity(
            pid=self.pid,
            process_start_identity=self.process_start_identity,
        )


@dataclass(frozen=True, slots=True)
class TaskSubmission:
    source: str
    file_path: str
    argv: tuple[str, ...]
    purpose: str | None
    origin_cwd: str
    dispatch: FrozenDispatchContext
    history_enabled: bool
    history_code_profile: str

    def __post_init__(self) -> None:
        if not isinstance(self.source, str):
            raise TypeError("source must be a string")
        if not isinstance(self.origin_cwd, str) or not self.origin_cwd.strip():
            raise ValueError("origin_cwd must not be empty")
        if not isinstance(self.file_path, str) or not self.file_path.strip():
            raise ValueError("file_path must not be empty")
        if not isinstance(self.argv, tuple) or not all(isinstance(value, str) for value in self.argv):
            raise TypeError("argv must be a tuple of strings")
        if self.purpose is not None and not isinstance(self.purpose, str):
            raise TypeError("purpose must be a string or None")
        if not isinstance(self.history_enabled, bool):
            raise TypeError("history_enabled must be a boolean")
        if not isinstance(self.history_code_profile, str) or not self.history_code_profile.strip():
            raise ValueError("history_code_profile must not be empty")
        object.__setattr__(self, "history_code_profile", self.history_code_profile.strip())

        origin = Path(self.origin_cwd).expanduser().resolve()
        source_path = Path(self.file_path).expanduser()
        if not source_path.is_absolute():
            source_path = origin / source_path
        object.__setattr__(self, "origin_cwd", str(origin))
        object.__setattr__(self, "file_path", str(source_path.resolve()))


@dataclass(frozen=True, slots=True)
class TaskRecord:
    id: str
    semantic_base: str
    ordinal: int
    status: TaskStatus
    source: str | None
    source_sha256: str
    file_path: str
    argv: tuple[str, ...]
    purpose: str | None
    origin_cwd: str
    dispatch: FrozenDispatchContext
    created_at: str
    started_at: str | None
    finished_at: str | None
    completion_resource_id: str | None
    history_enabled: bool
    history_code_profile: str
    runtime_failure_code: str | None
    runtime_failure_message: str | None
    runtime_failure_detail: str | None
