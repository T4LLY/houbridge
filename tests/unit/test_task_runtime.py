from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from houbridge.process_coordination import ProcessIdentity
from houbridge.semantic_id import SemanticBase
from houbridge.session.probe import SessionProbeResult
from houbridge.task import (
    FrozenDispatchContext,
    TaskRuntime,
    TaskRuntimeStateStore,
    TaskRuntimeSupervisor,
    TaskStore,
    TaskSubmission,
    TaskTargetValidator,
)


class FixedSemanticGenerator:
    def generate(self, _text: str, *, fallback_stem: str) -> SemanticBase:
        assert fallback_stem == "task-unknown"
        return SemanticBase(prefix="runtime-work-item", tags=("runtime", "work", "item"))


def _store(tmp_path: Path) -> TaskStore:
    return TaskStore(
        tmp_path / "tasks.db",
        semantic_generator=FixedSemanticGenerator(),
        now=lambda: datetime(2026, 9, 11, 9, 0, tzinfo=timezone.utc),
    )


def _runtime_state(store: TaskStore) -> TaskRuntimeStateStore:
    return TaskRuntimeStateStore(
        store.database,
        now=lambda: datetime(2026, 9, 11, 9, 0, tzinfo=timezone.utc),
    )


def _submit(store: TaskStore, index: int, *, pid: int, identity: str | None = None) -> str:
    process_identity = identity or f"process-{pid}"
    task = store.submit(
        TaskSubmission(
            source=f"print({index})\n",
            file_path=f"/workspace/task-{index}.py",
            argv=(f"task-{index}.py",),
            purpose=None,
            origin_cwd="/workspace",
            dispatch=FrozenDispatchContext(
                session=index + 1,
                port=17000 + index,
                pid=pid,
                process_start_identity=process_identity,
                transport_executable="/opt/hfs/bin/hcommand",
                transport_timeout_seconds=10,
                transport_environment={"HFS": "/opt/hfs"},
                lock_timeout_seconds=5,
            ),
            history_enabled=False,
            history_code_profile="profile-a",
        )
    )
    return task.id


class AcceptTarget:
    def validate(self, _task) -> None:
        return None


class CompletingRunner:
    def __init__(self, store: TaskStore, *, hold: threading.Event | None = None) -> None:
        self.store = store
        self.hold = hold
        self._lock = threading.Lock()
        self.active = 0
        self.max_active = 0
        self.two_active = threading.Event()
        self.run_ids: list[str] = []
        self.recover_ids: list[str] = []

    def run(self, task) -> None:
        self.store.mark_running(task.id)
        with self._lock:
            self.run_ids.append(task.id)
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            if self.active >= 2:
                self.two_active.set()
        if self.hold is not None:
            assert self.hold.wait(5)
        else:
            time.sleep(0.03)
        self.store.mark_completed(task.id)
        with self._lock:
            self.active -= 1

    def recover(self, task) -> None:
        self.recover_ids.append(task.id)
        self.store.mark_completed(task.id)

    def runtime_failed(self, task, error) -> None:
        self.store.mark_runtime_failed(
            task.id,
            code=error.code,
            message=error.message,
            detail=error.detail,
        )

    def cleanup_terminal_workspaces(self) -> None:
        return None


def _reserve(state: TaskRuntimeStateStore, token: str = "runtime-token") -> None:
    assert state.reserve_runtime_start(token, ProcessIdentity(9001, "starter"))


def test_runtime_enforces_global_max_concurrency_for_different_processes(tmp_path: Path) -> None:
    store = _store(tmp_path)
    ids = [_submit(store, index, pid=1000 + index) for index in range(3)]
    state = _runtime_state(store)
    _reserve(state)
    release = threading.Event()
    runner = CompletingRunner(store, hold=release)
    runtime = TaskRuntime(
        store,
        state,
        runner,
        max_concurrency=2,
        target_validator=AcceptTarget(),
    )

    thread = threading.Thread(
        target=runtime.run,
        args=("runtime-token",),
        kwargs={"runtime_identity": ProcessIdentity(9002, "runtime")},
    )
    thread.start()
    assert runner.two_active.wait(5)
    assert runner.max_active == 2
    assert state.claim_count() == 2
    release.set()
    thread.join(5)
    assert not thread.is_alive()
    assert all(store.get(task_id).status == "completed" for task_id in ids)  # type: ignore[union-attr]
    assert state.runtime_owner() is None


def test_same_process_tasks_are_serialized_even_with_global_capacity(tmp_path: Path) -> None:
    store = _store(tmp_path)
    ids = [_submit(store, index, pid=3000, identity="same-incarnation") for index in range(2)]
    state = _runtime_state(store)
    _reserve(state)
    runner = CompletingRunner(store)
    runtime = TaskRuntime(
        store,
        state,
        runner,
        max_concurrency=2,
        target_validator=AcceptTarget(),
    )

    runtime.run("runtime-token", runtime_identity=ProcessIdentity(9002, "runtime"))

    assert runner.max_active == 1
    assert runner.run_ids == ids
    assert all(store.get(task_id).status == "completed" for task_id in ids)  # type: ignore[union-attr]


def test_runtime_rejects_restarted_bound_target_without_dispatch(tmp_path: Path) -> None:
    store = _store(tmp_path)
    task_id = _submit(store, 0, pid=4100, identity="old-incarnation")
    state = _runtime_state(store)
    _reserve(state)
    runner = CompletingRunner(store)
    expected = ProcessIdentity(4100, "old-incarnation")
    validator = TaskTargetValidator(
        identity_reader=lambda _pid: expected,
        probe=lambda dispatch: SessionProbeResult(
            pid=9999,
            version="21.0.440",
            license="Houdini FX",
            file=None,
            headless=False,
            open_ports=(dispatch.port,),
        ),
    )
    runtime = TaskRuntime(
        store,
        state,
        runner,
        max_concurrency=1,
        target_validator=validator,
    )

    runtime.run("runtime-token", runtime_identity=ProcessIdentity(9002, "runtime"))

    task = store.get(task_id)
    assert task is not None
    assert task.status == "failed"
    assert task.runtime_failure_code == "task_target_changed"
    assert runner.run_ids == []


def test_replacement_runtime_recovers_running_claim_without_replaying_run(tmp_path: Path) -> None:
    store = _store(tmp_path)
    task_id = _submit(store, 0, pid=5100)
    state = _runtime_state(store)
    _reserve(state, "dead-owner")
    assert state.claim_runtime_owner("dead-owner", ProcessIdentity(9100, "dead-runtime"))
    claimed_id = state.claim_next_queued("dead-owner", max_concurrency=1)
    assert claimed_id == task_id
    store.mark_running(task_id)
    assert state.clear_runtime_owner("dead-owner")
    assert state.reserve_runtime_start("replacement", ProcessIdentity(9200, "starter"))

    runner = CompletingRunner(store)
    runtime = TaskRuntime(
        store,
        state,
        runner,
        max_concurrency=1,
        target_validator=AcceptTarget(),
    )
    runtime.run("replacement", runtime_identity=ProcessIdentity(9201, "replacement-runtime"))

    assert runner.run_ids == []
    assert runner.recover_ids == [task_id]
    assert store.get(task_id).status == "completed"  # type: ignore[union-attr]


def test_supervisor_lazily_replaces_stale_runtime_ownership(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _submit(store, 0, pid=6100)
    state = _runtime_state(store)
    assert state.reserve_runtime_start("dead-owner", ProcessIdentity(9300, "dead-starter"))
    assert state.claim_runtime_owner("dead-owner", ProcessIdentity(9301, "dead-runtime"))

    def identity_reader(pid: int) -> ProcessIdentity:
        if pid == 9301:
            raise ProcessLookupError(pid)
        if pid == 9400:
            return ProcessIdentity(9400, "new-starter")
        raise AssertionError(f"unexpected pid {pid}")

    launched: list[str] = []
    supervisor = TaskRuntimeSupervisor(
        state,
        identity_reader=identity_reader,
        current_identity_reader=lambda: ProcessIdentity(9400, "new-starter"),
        token_factory=lambda: "replacement-token",
    )

    assert supervisor.ensure_active(launched.append) is True
    assert launched == ["replacement-token"]
    owner = state.runtime_owner()
    assert owner is not None
    assert owner.token == "replacement-token"
    assert owner.runtime_identity is None
    assert supervisor.ensure_active(launched.append) is False
    assert launched == ["replacement-token"]


def test_retirement_and_submit_handshake_does_not_strand_new_work(tmp_path: Path) -> None:
    store = _store(tmp_path)
    state = _runtime_state(store)
    assert state.reserve_runtime_start("owner", ProcessIdentity(9500, "runtime"))
    assert state.claim_runtime_owner("owner", ProcessIdentity(9500, "runtime"))
    assert state.retire_runtime_if_idle("owner") is True

    _submit(store, 0, pid=7100)
    launched: list[str] = []
    supervisor = TaskRuntimeSupervisor(
        state,
        identity_reader=lambda pid: ProcessIdentity(pid, "starter"),
        current_identity_reader=lambda: ProcessIdentity(9600, "starter"),
        token_factory=lambda: "after-retirement",
    )
    assert supervisor.ensure_active(launched.append) is True
    assert launched == ["after-retirement"]

    # Opposite ordering: committed queued work prevents an active owner from
    # retiring, so the current runtime observes it instead of stranding it.
    state.clear_runtime_owner("after-retirement")
    assert state.reserve_runtime_start("owner-2", ProcessIdentity(9700, "runtime-2"))
    assert state.claim_runtime_owner("owner-2", ProcessIdentity(9700, "runtime-2"))
    assert state.retire_runtime_if_idle("owner-2") is False


def test_claim_capacity_is_shared_across_runtime_state_instances(tmp_path: Path) -> None:
    store = _store(tmp_path)
    ids = [_submit(store, index, pid=8100 + index) for index in range(3)]
    first_state = _runtime_state(store)
    second_state = _runtime_state(store)
    _reserve(first_state, "shared-owner")
    assert first_state.claim_runtime_owner(
        "shared-owner",
        ProcessIdentity(9800, "runtime"),
    )

    first = first_state.claim_next_queued("shared-owner", max_concurrency=2)
    second = second_state.claim_next_queued("shared-owner", max_concurrency=2)
    third = first_state.claim_next_queued("shared-owner", max_concurrency=2)

    assert {first, second}.issubset(set(ids))
    assert first != second
    assert third is None
    assert first_state.claim_count() == second_state.claim_count() == 2


def test_replacement_runtime_adopts_queued_task_once_dispatch_state_exists(tmp_path: Path) -> None:
    from houbridge.task import TaskInvocationStore

    store = _store(tmp_path)
    task_id = _submit(store, 0, pid=8800)
    state = _runtime_state(store)
    _reserve(state, "dead-owner")
    assert state.claim_runtime_owner("dead-owner", ProcessIdentity(9800, "dead-runtime"))
    assert state.claim_next_queued("dead-owner", max_concurrency=1) == task_id
    invocations = TaskInvocationStore(store.database)
    invocations.create(task_id, tmp_path / "recoverable-workspace")
    assert state.clear_runtime_owner("dead-owner")
    assert state.reserve_runtime_start("replacement", ProcessIdentity(9801, "starter"))

    class RecoverQueuedRunner(CompletingRunner):
        def run(self, task) -> None:
            raise AssertionError("queued Task with dispatch state must not be replayed")

        def recover(self, task) -> None:
            self.recover_ids.append(task.id)
            if task.status == "queued":
                self.store.mark_running(task.id)
            self.store.mark_completed(task.id)
            invocations.remove(task.id)

    runner = RecoverQueuedRunner(store)
    runtime = TaskRuntime(
        store,
        state,
        runner,
        max_concurrency=1,
        target_validator=AcceptTarget(),
    )
    runtime.run("replacement", runtime_identity=ProcessIdentity(9802, "replacement-runtime"))

    assert runner.run_ids == []
    assert runner.recover_ids == [task_id]
    assert store.get(task_id).status == "completed"  # type: ignore[union-attr]
