from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from houbridge.capture.sequence import CaptureSequenceAllocator
from houbridge.process_coordination import (
    InterprocessFileLock,
    InterprocessFileLockTimeout,
)


@pytest.mark.parametrize("operation", ["reserve", "cleanup"])
def test_sequence_lock_wait_is_bounded_while_another_thread_holds_lock(
    tmp_path: Path, operation: str
) -> None:
    timeout = 0.05
    allocator = CaptureSequenceAllocator(
        tmp_path / "artifacts",
        "capture",
        lock_timeout_seconds=timeout,
    )
    state_directory = allocator._state_directory()
    lock_path = state_directory / "sequence.lock"
    attempted = threading.Event()
    errors: list[BaseException] = []

    def run_operation() -> None:
        attempted.set()
        try:
            if operation == "reserve":
                allocator.reserve("viewport-20261003-1200")
            else:
                allocator.cleanup_before(float("inf"))
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(target=run_operation)
    started = time.monotonic()
    with InterprocessFileLock().acquire(lock_path, timeout_seconds=1):
        thread.start()
        assert attempted.wait(1)
        thread.join(1)
        assert not thread.is_alive()
    thread.join(1)

    assert len(errors) == 1
    assert isinstance(errors[0], InterprocessFileLockTimeout)
    assert timeout <= time.monotonic() - started < 1


def test_concurrent_sequence_reservations_are_unique(tmp_path: Path) -> None:
    allocator = CaptureSequenceAllocator(tmp_path / "artifacts", "capture")

    with ThreadPoolExecutor(max_workers=8) as executor:
        sequences = list(
            executor.map(
                lambda _index: allocator.reserve("viewport-20261003-1200"),
                range(32),
            )
        )

    assert sorted(sequences) == list(range(1, 33))
