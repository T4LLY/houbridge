from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from houbridge._temporary_fs import atomic_write_bytes
from houbridge.process_coordination import InterprocessFileLock


_STATE_DIRECTORY = ".capture-sequences"
_LOCK_FILENAME = "sequence.lock"


@dataclass(slots=True)
class CaptureSequenceAllocator:
    """Allocate durable per-minute capture sequence numbers across CLI processes."""

    artifacts_root: Path
    namespace: str
    _file_lock: InterprocessFileLock = field(
        default_factory=InterprocessFileLock,
        repr=False,
    )
    lock_timeout_seconds: float = 120.0

    def reserve(self, key: str) -> int:
        state_directory = self._state_directory()
        lock_path = state_directory / _LOCK_FILENAME
        with self._file_lock.acquire(
            lock_path,
            timeout_seconds=self.lock_timeout_seconds,
        ):
            state_path = state_directory / f"{key}.seq"
            last_reserved = self._read_last_reserved(state_path)
            existing_max = self._existing_max_sequence(key)
            sequence = max(last_reserved, existing_max) + 1
            atomic_write_bytes(state_path, f"{sequence}\n".encode("ascii"))
            return sequence

    def cleanup_before(self, cutoff_timestamp: float) -> int:
        state_directory = self.artifacts_root / _STATE_DIRECTORY
        if not state_directory.is_dir():
            return 0

        removed = 0
        lock_path = state_directory / _LOCK_FILENAME
        with self._file_lock.acquire(
            lock_path,
            timeout_seconds=self.lock_timeout_seconds,
        ):
            for path in state_directory.glob("*.seq"):
                try:
                    if path.stat().st_mtime <= cutoff_timestamp:
                        path.unlink()
                        removed += 1
                except FileNotFoundError:
                    continue
        return removed

    def _state_directory(self) -> Path:
        directory = self.artifacts_root / _STATE_DIRECTORY
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    @staticmethod
    def _read_last_reserved(path: Path) -> int:
        try:
            raw = path.read_text(encoding="ascii").strip()
        except FileNotFoundError:
            return 0
        try:
            value = int(raw)
        except ValueError as exc:
            raise ValueError(f"Invalid capture sequence state: {path}") from exc
        if value < 0:
            raise ValueError(f"Invalid capture sequence state: {path}")
        return value

    def _existing_max_sequence(self, key: str) -> int:
        directory = self.artifacts_root / self.namespace
        if not directory.is_dir():
            return 0

        prefix = f"{key}-"
        maximum = 0
        for path in directory.iterdir():
            if not path.is_file() or not path.name.startswith(prefix):
                continue
            remainder = path.name[len(prefix) :]
            sequence_text = remainder.split(".", 1)[0]
            if sequence_text.isdigit():
                maximum = max(maximum, int(sequence_text))
        return maximum
