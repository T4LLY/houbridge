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


def process_identity_for_pid(pid: int) -> ProcessIdentity:
    """Resolve the current operating-system incarnation for ``pid``.

    Session resolution uses this before and after the Houdini probe so a PID
    recycle during validation cannot be mistaken for the recorded process.
    """

    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
        raise ValueError("pid must be a positive integer")

    if os.name == "nt":
        identity = _windows_process_start_identity(pid)
    elif _linux_proc_stat_path(pid).exists():
        identity = _linux_process_start_identity(pid)
    else:
        identity = _posix_process_start_identity(pid)
    return ProcessIdentity(pid=pid, process_start_identity=identity)


def _linux_proc_stat_path(pid: int) -> Path:
    return Path("/proc") / str(pid) / "stat"


def _linux_process_start_identity(pid: int) -> str:
    try:
        stat_text = _linux_proc_stat_path(pid).read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ProcessLookupError(pid) from exc
    except OSError:
        raise

    closing_paren = stat_text.rfind(")")
    if closing_paren < 0:
        raise OSError(f"Unable to parse process stat for PID {pid}.")
    fields = stat_text[closing_paren + 2 :].split()
    # /proc/<pid>/stat field 22 is starttime. The sliced list begins at field 3.
    if len(fields) <= 19:
        raise OSError(f"Unable to parse process start identity for PID {pid}.")
    start_ticks = fields[19]
    try:
        boot_id = Path("/proc/sys/kernel/random/boot_id").read_text(encoding="ascii").strip()
    except OSError:
        boot_id = "unknown-boot"
    return f"linux:{boot_id}:{start_ticks}"


def _windows_process_start_identity(pid: int) -> str:
    import ctypes
    from ctypes import wintypes

    process_query_limited_information = 0x1000
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.GetProcessTimes.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
    ]
    kernel32.GetProcessTimes.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
    if not handle:
        error = ctypes.get_last_error()
        if error in {87, 1168}:  # invalid parameter / not found
            raise ProcessLookupError(pid)
        raise OSError(error, f"OpenProcess failed for PID {pid}.")

    creation = wintypes.FILETIME()
    exit_time = wintypes.FILETIME()
    kernel = wintypes.FILETIME()
    user = wintypes.FILETIME()
    try:
        if not kernel32.GetProcessTimes(
            handle,
            ctypes.byref(creation),
            ctypes.byref(exit_time),
            ctypes.byref(kernel),
            ctypes.byref(user),
        ):
            error = ctypes.get_last_error()
            raise OSError(error, f"GetProcessTimes failed for PID {pid}.")
    finally:
        kernel32.CloseHandle(handle)

    creation_ticks = (int(creation.dwHighDateTime) << 32) | int(creation.dwLowDateTime)
    return f"windows:{creation_ticks}"


def _posix_process_start_identity(pid: int) -> str:
    import subprocess

    try:
        completed = subprocess.run(
            ["ps", "-o", "lstart=", "-p", str(pid)],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError:
        raise
    value = completed.stdout.strip()
    if completed.returncode != 0 or not value:
        raise ProcessLookupError(pid)
    return f"posix:{value}"
