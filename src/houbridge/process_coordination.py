from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import errno
import hashlib
import os
from pathlib import Path
import time
from typing import BinaryIO, Iterator

from platformdirs import user_runtime_path


_DEFAULT_POLL_INTERVAL_SECONDS = 0.05


@dataclass(frozen=True, slots=True)
class ProcessIdentity:
    """Exact identity for one operating-system Houdini process incarnation."""

    pid: int
    process_start_identity: str

    def __post_init__(self) -> None:
        if isinstance(self.pid, bool) or not isinstance(self.pid, int) or self.pid <= 0:
            raise ValueError("pid must be a positive integer")
        if not isinstance(self.process_start_identity, str):
            raise TypeError("process_start_identity must be a string")
        normalized = self.process_start_identity.strip()
        if not normalized:
            raise ValueError("process_start_identity must not be empty")
        object.__setattr__(self, "process_start_identity", normalized)

    @classmethod
    def normalize(
        cls,
        pid: int,
        process_start_identity: str | int,
    ) -> "ProcessIdentity":
        if isinstance(process_start_identity, bool):
            raise TypeError("process_start_identity must be a string or integer")
        if isinstance(process_start_identity, int):
            normalized = str(process_start_identity)
        elif isinstance(process_start_identity, str):
            normalized = process_start_identity.strip()
        else:
            raise TypeError("process_start_identity must be a string or integer")
        return cls(pid=pid, process_start_identity=normalized)

    def _coordination_digest(self) -> str:
        incarnation = self.process_start_identity.encode("utf-8")
        canonical = (
            str(self.pid).encode("ascii")
            + b":"
            + str(len(incarnation)).encode("ascii")
            + b":"
            + incarnation
        )
        return hashlib.sha256(canonical).hexdigest()


def coordination_directory() -> Path:
    """Return the fixed per-user runtime directory for process coordination."""

    return user_runtime_path("houbridge", ensure_exists=False) / "coordination"


class ManagedExecutionLockTimeout(TimeoutError):
    def __init__(self, identity: ProcessIdentity) -> None:
        super().__init__(
            "Timed out waiting for managed execution lock for "
            f"PID {identity.pid} process incarnation."
        )
        self.identity = identity


class ManagedExecutionLock:
    """Serialize managed Python dispatch by exact Houdini process identity."""

    def __init__(self, *, poll_interval_seconds: float = _DEFAULT_POLL_INTERVAL_SECONDS) -> None:
        if poll_interval_seconds <= 0:
            raise ValueError("poll_interval_seconds must be greater than zero")
        self._poll_interval_seconds = float(poll_interval_seconds)

    @contextmanager
    def acquire(
        self,
        identity: ProcessIdentity,
        *,
        timeout_seconds: float | None = None,
    ) -> Iterator[None]:
        if timeout_seconds is not None and timeout_seconds < 0:
            raise ValueError("timeout_seconds must be non-negative or None")

        lock_dir = coordination_directory() / "managed-execution"
        lock_dir.mkdir(parents=True, exist_ok=True)
        lock_path = lock_dir / (
            f"pid-{identity.pid}-{identity._coordination_digest()[:32]}.lock"
        )

        with lock_path.open("a+b") as handle:
            _ensure_lock_byte(handle)
            deadline = None if timeout_seconds is None else time.monotonic() + timeout_seconds
            while True:
                try:
                    _try_lock(handle)
                    break
                except BlockingIOError:
                    if deadline is not None and time.monotonic() >= deadline:
                        raise ManagedExecutionLockTimeout(identity) from None
                    sleep_for = self._poll_interval_seconds
                    if deadline is not None:
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            raise ManagedExecutionLockTimeout(identity) from None
                        sleep_for = min(sleep_for, remaining)
                    time.sleep(sleep_for)

            try:
                yield
            finally:
                _unlock(handle)


def _ensure_lock_byte(handle: BinaryIO) -> None:
    handle.seek(0, os.SEEK_END)
    if handle.tell() == 0:
        handle.write(b"\0")
        handle.flush()
    handle.seek(0)


if os.name == "nt":
    import msvcrt

    def _try_lock(handle: BinaryIO) -> None:
        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            if exc.errno in {errno.EACCES, errno.EAGAIN, errno.EDEADLK, errno.EPERM}:
                raise BlockingIOError from exc
            raise

    def _unlock(handle: BinaryIO) -> None:
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)

else:
    import fcntl

    def _try_lock(handle: BinaryIO) -> None:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno in {errno.EACCES, errno.EAGAIN}:
                raise BlockingIOError from exc
            raise

    def _unlock(handle: BinaryIO) -> None:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
