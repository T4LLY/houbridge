from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from houbridge.cli import task_cmd
from houbridge.cli.main import app
from houbridge.errors import BridgeError
from houbridge.semantic_id import SemanticBase
from houbridge.task.completion import TaskCompletionResourceFinalizer
from houbridge.task.models import FrozenDispatchContext, TaskSubmission
from houbridge.task.service import TaskCommandService
from houbridge.task.store import TaskStore


class FixedSemanticGenerator:
    def generate(self, _text: str, *, fallback_stem: str) -> SemanticBase:
        assert fallback_stem == "task-unknown"
        return SemanticBase(prefix="geometry-build-cache", tags=("geometry", "build", "cache"))


def _submission(source: str = "print('x')\n") -> TaskSubmission:
    return TaskSubmission(
        source=source,
        file_path="/workspace/build.py",
        argv=("--quality", "high"),
        purpose=None,
        origin_cwd="/workspace",
        dispatch=FrozenDispatchContext(
            session=1,
            port=1714,
            pid=4242,
            process_start_identity="start-4242",
            transport_executable="hcommand",
            transport_timeout_seconds=5,
            transport_environment={},
            lock_timeout_seconds=5,
        ),
        history_enabled=False,
        history_code_profile="profile-a",
    )


def _store(tmp_path: Path, *, now: datetime | None = None) -> TaskStore:
    return TaskStore(
        tmp_path / "tasks.db",
        semantic_generator=FixedSemanticGenerator(),
        now=(lambda: now) if now is not None else None,
    )


class CapturingResourceStore:
    def __init__(self) -> None:
        self.payloads: list[bytes] = []

    def put_bytes(self, payload: bytes):
        self.payloads.append(payload)
        return SimpleNamespace(semantic_alias="task-output-000")


class FailingResourceStore:
    def put_bytes(self, payload: bytes):
        raise BridgeError("resource_store_failed", "boom")


def test_success_finalization_creates_exact_stdout_stderr_resource_before_completed(tmp_path: Path) -> None:
    store = _store(tmp_path)
    task = store.submit(_submission())
    store.mark_running(task.id)
    store.append_stream(task.id, "stdout", "10%\n100%\n")
    store.append_stream(task.id, "stderr", "warn\n")
    resources = CapturingResourceStore()

    TaskCompletionResourceFinalizer(store, resources).finalize_success(store.get(task.id))  # type: ignore[arg-type]

    assert resources.payloads == [b'{"stdout":"10%\\n100%\\n","stderr":"warn\\n"}']
    completed = store.get(task.id)
    assert completed is not None
    assert completed.status == "completed"
    assert completed.completion_resource_id == "task-output-000"


def test_resource_finalization_failure_marks_task_failed_and_keeps_streams(tmp_path: Path) -> None:
    store = _store(tmp_path)
    task = store.submit(_submission())
    store.mark_running(task.id)
    store.append_stream(task.id, "stdout", "partial\n")

    TaskCompletionResourceFinalizer(store, FailingResourceStore()).finalize_success(store.get(task.id))  # type: ignore[arg-type]

    failed = store.get(task.id)
    assert failed is not None
    assert failed.status == "failed"
    assert failed.runtime_failure_code == "task_resource_finalization_failed"
    assert store.accumulated_stream(task.id, "stdout") == "partial\n"


def test_terminal_retention_uses_finished_time_and_preserves_ordinals(tmp_path: Path) -> None:
    base = datetime(2026, 9, 1, tzinfo=timezone.utc)
    store = _store(tmp_path, now=base)
    old = store.submit(_submission())
    store.mark_runtime_failed(old.id, code="x", message="x", finished_at=base)
    active = store.submit(_submission("print('active')\n"))

    assert store.cleanup_expired(ttl_hours=72, now=base + timedelta(hours=73)) == 1
    assert store.get(old.id) is None
    assert store.get(active.id) is not None
    next_task = store.submit(_submission())
    assert next_task.id == "geometry-build-cache-002"


def test_reset_rejects_active_and_resets_terminal_ordinal_state(tmp_path: Path) -> None:
    store = _store(tmp_path)
    active = store.submit(_submission())
    with pytest.raises(BridgeError) as exc_info:
        store.reset()
    assert exc_info.value.code == "task_reset_active"

    store.mark_runtime_failed(active.id, code="x", message="x")
    store.reset()
    assert store.list_tasks() == ()
    fresh = store.submit(_submission())
    assert fresh.id == "geometry-build-cache-000"


class NoopSupervisor:
    def __init__(self) -> None:
        self.calls = 0

    def ensure_active(self, launcher) -> bool:
        self.calls += 1
        return False


def test_task_service_shapes_and_list_order(tmp_path: Path) -> None:
    store = _store(tmp_path)
    queued = store.submit(_submission("print('one')\n"))
    running = store.submit(_submission("print('two')\n"))
    store.mark_running(running.id)
    store.append_stream(running.id, "stdout", "10%\n")
    supervisor = NoopSupervisor()
    service = TaskCommandService(store, supervisor, lambda _token: None, ttl_hours=72)  # type: ignore[arg-type]

    expected_file = str(Path("/workspace/build.py").resolve())
    assert service.get(queued.id) == {
        "id": queued.id,
        "status": "queued",
        "file": expected_file,
        "args": ["--quality", "high"],
    }
    assert service.get(running.id) == {
        "id": running.id,
        "status": "running",
        "file": expected_file,
        "args": ["--quality", "high"],
        "stdout": "10%\n",
        "stderr": "",
    }
    listed = service.list()["tasks"]
    assert [item["id"] for item in listed] == [running.id, queued.id]
    assert all(set(item) == {"id", "status", "file", "args"} for item in listed)
    assert supervisor.calls == 3


def test_task_get_missing_uses_shared_error_envelope(monkeypatch) -> None:
    class Service:
        def get(self, task_id: str):
            raise BridgeError("task_not_found", f"Task does not exist: {task_id}")

    monkeypatch.setattr(task_cmd, "load_config", lambda: object())
    monkeypatch.setattr(task_cmd, "_service", lambda _settings: Service())
    result = CliRunner().invoke(app, ["task", "get", "missing-task"])
    assert result.exit_code == 1
    assert json.loads(result.stdout) == {
        "error": True,
        "code": "task_not_found",
        "message": "Task does not exist: missing-task",
    }


def test_task_help_exposes_only_get_list_reset() -> None:
    result = CliRunner().invoke(app, ["task", "--help"])
    assert result.exit_code == 0
    for command in ("get", "list", "reset"):
        assert command in result.stdout
    for removed in ("cancel", "wait", "progress", "--root"):
        assert removed not in result.stdout


def test_async_handoff_failure_does_not_leave_queued_task(tmp_path: Path) -> None:
    from houbridge.execution.models import ExecutionInvocation
    from houbridge.process_coordination import ProcessIdentity
    from houbridge.task.async_submission import AsyncExecutionSubmitter

    store = _store(tmp_path)

    class Resolver:
        def resolve(self, session):
            return SimpleNamespace(
                record=SimpleNamespace(session=1, port=1714),
                identity=ProcessIdentity(4242, "start-4242"),
            )

    class Transport:
        executable = "hcommand"
        timeout_seconds = 3.0

        def subprocess_environment(self):
            return {}

    class Supervisor:
        def ensure_active(self, launcher):
            raise BridgeError("task_runtime_handoff_timeout", "handoff timed out")

    submitter = AsyncExecutionSubmitter(
        Resolver(),  # type: ignore[arg-type]
        Transport(),  # type: ignore[arg-type]
        store,
        Supervisor(),  # type: ignore[arg-type]
        lambda _token: None,
        lock_timeout_seconds=5,
        history_enabled=False,
        history_code_profile="profile-a",
        ttl_hours=72,
    )
    invocation = ExecutionInvocation(
        source="print('x')\n",
        source_path="/workspace/build.py",
        argv=("/workspace/build.py",),
        purpose=None,
        origin_cwd="/workspace",
    )

    with pytest.raises(BridgeError) as exc_info:
        submitter.submit(invocation, session=1)
    assert exc_info.value.code == "task_runtime_handoff_timeout"
    tasks = store.list_tasks()
    assert len(tasks) == 1
    assert tasks[0].status == "failed"
    assert tasks[0].runtime_failure_code == "task_runtime_handoff_failed"
