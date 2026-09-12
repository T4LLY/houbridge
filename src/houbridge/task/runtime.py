from __future__ import annotations

import os
from collections import deque
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from typing import Protocol

from houbridge.errors import BridgeError
from houbridge.process_coordination import ManagedExecutionLock, ProcessIdentity, process_identity_for_pid

from .models import TaskRecord
from .runtime_store import TaskRuntimeStateStore
from .store import TaskStore
from .target import TaskTargetValidator


class TaskRunner(Protocol):
    """Execution boundary for one claimed Task invocation.

    ``run`` is only called for a queued Task that passed exact-target validation.
    ``recover`` is called for a Task whose prior runtime already established
    invocation recovery state, whether its public status is still queued or has
    reached running. Marker and stream semantics stay behind this boundary so
    the scheduler never guesses whether caller Python has started.
    """

    def run(self, task: TaskRecord) -> None:
        ...

    def recover(self, task: TaskRecord) -> None:
        ...

    def runtime_failed(self, task: TaskRecord, error: BridgeError) -> None:
        ...

    def cleanup_terminal_workspaces(self) -> None:
        ...


class TaskRuntime:
    """On-demand queue scheduler over shared tasks.db claims."""

    def __init__(
        self,
        store: TaskStore,
        runtime_state: TaskRuntimeStateStore,
        runner: TaskRunner,
        *,
        max_concurrency: int,
        execution_lock: ManagedExecutionLock | None = None,
        target_validator: TaskTargetValidator | None = None,
    ) -> None:
        if isinstance(max_concurrency, bool) or not isinstance(max_concurrency, int) or max_concurrency < 1:
            raise ValueError("max_concurrency must be an integer >= 1")
        self._store = store
        self._runtime_state = runtime_state
        self._runner = runner
        self._max_concurrency = max_concurrency
        self._execution_lock = execution_lock or ManagedExecutionLock()
        self._target_validator = target_validator or TaskTargetValidator()

    def run(
        self,
        owner_token: str,
        *,
        runtime_identity: ProcessIdentity | None = None,
    ) -> None:
        identity = runtime_identity or process_identity_for_pid(os.getpid())
        if not self._runtime_state.claim_runtime_owner(owner_token, identity):
            raise BridgeError(
                "task_runtime_ownership_lost",
                "Task Runtime could not claim the reserved global Task ownership.",
            )

        self._runner.cleanup_terminal_workspaces()
        recovery_queue = deque(self._runtime_state.adopt_runtime_claims(owner_token))
        active_ids: set[str] = set()
        futures: dict[Future[None], str] = {}

        try:
            with ThreadPoolExecutor(
                max_workers=self._max_concurrency,
                thread_name_prefix="houbridge-task",
            ) as executor:
                while True:
                    while len(futures) < self._max_concurrency:
                        recovery_id = _take_unscheduled(recovery_queue, active_ids)
                        if recovery_id is not None:
                            recovery = self._require_task(recovery_id)
                            active_ids.add(recovery.id)
                            future = executor.submit(self._recover_claimed, recovery, owner_token)
                            futures[future] = recovery.id
                            continue

                        task_id = self._runtime_state.claim_next_queued(
                            owner_token,
                            max_concurrency=self._max_concurrency,
                        )
                        if task_id is None:
                            break
                        task = self._require_task(task_id)
                        active_ids.add(task.id)
                        future = executor.submit(self._run_claimed, task, owner_token)
                        futures[future] = task.id

                    if futures:
                        done, _pending = wait(tuple(futures), return_when=FIRST_COMPLETED)
                        for future in done:
                            task_id = futures.pop(future)
                            active_ids.discard(task_id)
                            future.result()
                        continue

                    running = tuple(
                        task_id
                        for task_id in self._runtime_state.recoverable_claims_for_owner(owner_token)
                        if task_id not in active_ids
                    )
                    if running:
                        recovery_queue.extend(running)
                        continue

                    self._runner.cleanup_terminal_workspaces()
                    if self._runtime_state.retire_runtime_if_idle(owner_token):
                        return

                    # A concurrent submission committed between our last claim
                    # attempt and the retirement transaction. Loop and claim it.
        except BaseException:
            # Claims remain Task-owned recovery state. Clearing only runtime
            # ownership lets a later Task operation activate a replacement.
            self._runtime_state.clear_runtime_owner(owner_token)
            raise

    def _require_task(self, task_id: str) -> TaskRecord:
        task = self._store.get(task_id)
        if task is None:
            raise BridgeError("task_not_found", f"Claimed Task does not exist: {task_id}")
        return task

    def _run_claimed(self, task: TaskRecord, owner_token: str) -> None:
        with self._execution_lock.acquire(
            task.dispatch.process_identity,
            timeout_seconds=task.dispatch.lock_timeout_seconds,
        ):
            if not self._validate_or_fail(task, owner_token):
                return
            self._runner.run(task)
            self._finish_claimed_call(task.id, owner_token, expected_before="queued")

    def _recover_claimed(self, task: TaskRecord, owner_token: str) -> None:
        with self._execution_lock.acquire(
            task.dispatch.process_identity,
            timeout_seconds=task.dispatch.lock_timeout_seconds,
        ):
            if not self._validate_or_fail(task, owner_token):
                return
            self._runner.recover(task)
            self._finish_claimed_call(task.id, owner_token, expected_before="running")

    def _validate_or_fail(self, task: TaskRecord, owner_token: str) -> bool:
        try:
            self._target_validator.validate(task)
        except BridgeError as exc:
            if exc.code != "task_target_changed":
                raise
            self._runner.runtime_failed(task, exc)
            self._runtime_state.release_claim(task.id, owner_token)
            return False
        return True

    def _finish_claimed_call(
        self,
        task_id: str,
        owner_token: str,
        *,
        expected_before: str,
    ) -> None:
        current = self._store.get(task_id)
        if current is None:
            raise BridgeError("task_not_found", f"Task disappeared while running: {task_id}")
        if current.status in ("completed", "failed"):
            self._runtime_state.release_claim(task_id, owner_token)
            return
        if expected_before == "queued" and current.status == "running":
            # A runner may return after observing its started marker. Keep the
            # claim and route it through recovery, never back through run().
            return
        raise BridgeError(
            "task_runtime_protocol",
            f"Task runner returned without a valid state transition for {task_id}.",
            f"status={current.status}",
        )


def _take_unscheduled(
    queue: deque[str],
    active_ids: set[str],
) -> str | None:
    while queue:
        task_id = queue.popleft()
        if task_id not in active_ids:
            return task_id
    return None
