from __future__ import annotations

import json
import sys
import threading
import time
import types
from pathlib import Path

import pytest

from houbridge.errors import BridgeError
from houbridge.process_coordination import ProcessIdentity
from houbridge.semantic_id import SemanticBase
from houbridge.task import (
    FrozenDispatchContext,
    TaskInvocationRunner,
    TaskInvocationStore,
    TaskStore,
    TaskSubmission,
)
from houbridge.task.streaming import TaskStreamCollector
from houbridge.temporary_workspace import TemporaryWorkspace, TemporaryWorkspaceService


class FixedSemanticGenerator:
    def generate(self, _text: str, *, fallback_stem: str) -> SemanticBase:
        assert fallback_stem == "task-unknown"
        return SemanticBase(prefix="stream-recovery-work", tags=("stream", "recovery", "work"))


def _store(tmp_path: Path) -> TaskStore:
    return TaskStore(tmp_path / "tasks.db", semantic_generator=FixedSemanticGenerator())


def _submit(store: TaskStore, *, timeout: float = 5.0, history: bool = False) -> str:
    return store.submit(
        TaskSubmission(
            source="print('hello')\n",
            file_path="/workspace/task.py",
            argv=("task.py",),
            purpose=None,
            origin_cwd="/workspace",
            dispatch=FrozenDispatchContext(
                session=1,
                port=1714,
                pid=4242,
                process_start_identity="process-4242",
                transport_executable="hcommand",
                transport_timeout_seconds=timeout,
                transport_environment={},
                lock_timeout_seconds=5,
            ),
            history_enabled=history,
            history_code_profile="profile-a",
        )
    ).id


class CompleteSuccess:
    def __init__(self, store: TaskStore) -> None:
        self.store = store
        self.calls: list[str] = []

    def finalize_success(self, task) -> None:
        self.calls.append(task.id)
        self.store.mark_completed(task.id)


class NeverDispatch:
    def __init__(self) -> None:
        self.calls = 0

    def start(self, task, script_path):
        self.calls += 1
        raise AssertionError("recovery must never re-dispatch submitted Python")


class _ThreadDispatchHandle:
    def __init__(self, thread: threading.Thread) -> None:
        self.thread = thread
        self.terminated = False

    def poll(self) -> int | None:
        return 0 if not self.thread.is_alive() else None

    def terminate(self) -> None:
        self.terminated = True


class StreamingDispatch:
    def __init__(self) -> None:
        self.first_written = threading.Event()
        self.finish = threading.Event()

    def start(self, task, script_path):
        directory = script_path.parent

        def writer() -> None:
            workspace = TemporaryWorkspace(directory)
            workspace.path_for("stdout.txt").write_bytes(b"")
            workspace.path_for("stderr.txt").write_bytes(b"")
            workspace.publish_marker(
                "started.json",
                json.dumps({"version": 1, "task_id": task.id}, separators=(",", ":")).encode(),
            )
            with workspace.path_for("stdout.txt").open("ab", buffering=0) as stream:
                stream.write("10%\n".encode())
                self.first_written.set()
                assert self.finish.wait(5)
                stream.write("20%\n".encode())
            workspace.publish_marker(
                "completion.json",
                json.dumps(
                    {"version": 1, "task_id": task.id, "python_ok": True},
                    separators=(",", ":"),
                ).encode(),
            )

        thread = threading.Thread(target=writer)
        thread.start()
        return _ThreadDispatchHandle(thread)


def _runner(
    store: TaskStore,
    tmp_path: Path,
    success,
    *,
    dispatcher=None,
    identity_reader=None,
) -> tuple[TaskInvocationRunner, TaskInvocationStore, TemporaryWorkspaceService]:
    invocations = TaskInvocationStore(store.database)
    workspaces = TemporaryWorkspaceService(temp_root=tmp_path / "temp")
    expected = ProcessIdentity(4242, "process-4242")
    return (
        TaskInvocationRunner(
            store,
            invocations,
            workspaces,
            success,
            dispatcher=dispatcher,
            identity_reader=identity_reader or (lambda _pid: expected),
            poll_interval_seconds=0.01,
        ),
        invocations,
        workspaces,
    )


def _publish_started(workspace: TemporaryWorkspace, task_id: str) -> None:
    workspace.publish_marker(
        "started.json",
        json.dumps({"version": 1, "task_id": task_id}, separators=(",", ":")).encode(),
    )


def _publish_completion(workspace: TemporaryWorkspace, task_id: str, python_ok: bool) -> None:
    workspace.publish_marker(
        "completion.json",
        json.dumps(
            {"version": 1, "task_id": task_id, "python_ok": python_ok},
            separators=(",", ":"),
        ).encode(),
    )


def _publish_python_finished(workspace: TemporaryWorkspace, task_id: str, python_ok: bool) -> None:
    workspace.publish_marker(
        "python-finished.json",
        json.dumps(
            {"version": 1, "task_id": task_id, "python_ok": python_ok},
            separators=(",", ":"),
        ).encode(),
    )


def _publish_wrapper_failed(workspace: TemporaryWorkspace, task_id: str, detail: str) -> None:
    workspace.publish_marker(
        "wrapper-failed.json",
        json.dumps(
            {"version": 1, "task_id": task_id, "detail": detail},
            separators=(",", ":"),
        ).encode(),
    )


def test_recovery_terminalizes_wrapper_failure_after_python_finished(tmp_path: Path) -> None:
    store = _store(tmp_path)
    task_id = _submit(store)
    runner, invocations, workspaces = _runner(store, tmp_path, CompleteSuccess(store))
    workspace = workspaces.allocate(prefix="task")
    invocations.create(task_id, workspace.directory)
    workspace.path_for("stdout.txt").write_text("done\n", encoding="utf-8")
    workspace.path_for("stderr.txt").write_text("", encoding="utf-8")
    _publish_started(workspace, task_id)
    _publish_python_finished(workspace, task_id, True)
    _publish_wrapper_failed(workspace, task_id, "OSError: simulated fsync failure")
    store.mark_running(task_id)

    task = store.get(task_id)
    assert task is not None
    runner.recover(task)

    failed = store.get(task_id)
    assert failed is not None
    assert failed.status == "failed"
    assert failed.runtime_failure_code == "task_wrapper_failed"
    assert failed.runtime_failure_detail == "OSError: simulated fsync failure"
    assert invocations.get(task_id) is None
    assert not workspace.directory.exists()


def test_live_monitor_terminalizes_exited_wrapper_after_python_finished(tmp_path: Path) -> None:
    store = _store(tmp_path)
    task_id = _submit(store)

    class ExitedHandle:
        def poll(self):
            return 7

        def terminate(self):
            raise AssertionError("post-start wrapper failure must not use dispatch-time termination")

    class Dispatcher:
        def start(self, task, script_path):
            workspace = TemporaryWorkspace(script_path.parent)
            workspace.path_for("stdout.txt").write_text("done\n", encoding="utf-8")
            workspace.path_for("stderr.txt").write_text("", encoding="utf-8")
            _publish_started(workspace, task.id)
            _publish_python_finished(workspace, task.id, True)
            return ExitedHandle()

    runner, _invocations, _workspaces = _runner(
        store,
        tmp_path,
        CompleteSuccess(store),
        dispatcher=Dispatcher(),
    )
    task = store.get(task_id)
    assert task is not None
    runner.run(task)

    failed = store.get(task_id)
    assert failed is not None
    assert failed.status == "failed"
    assert failed.runtime_failure_code == "task_wrapper_failed"
    assert "status=7" in (failed.runtime_failure_detail or "")


def test_running_stream_is_incrementally_committed_and_reads_accumulate(tmp_path: Path) -> None:
    store = _store(tmp_path)
    task_id = _submit(store)
    dispatcher = StreamingDispatch()
    success = CompleteSuccess(store)
    runner, _invocations, _workspaces = _runner(
        store,
        tmp_path,
        success,
        dispatcher=dispatcher,
    )
    task = store.get(task_id)
    assert task is not None

    thread = threading.Thread(target=runner.run, args=(task,))
    thread.start()
    assert dispatcher.first_written.wait(5)
    deadline = time.monotonic() + 5
    while store.accumulated_stream(task_id, "stdout") != "10%\n":
        assert time.monotonic() < deadline
        time.sleep(0.01)
    assert store.get(task_id).status == "running"  # type: ignore[union-attr]

    dispatcher.finish.set()
    thread.join(5)
    assert not thread.is_alive()
    assert store.accumulated_stream(task_id, "stdout") == "10%\n20%\n"
    assert store.get(task_id).status == "completed"  # type: ignore[union-attr]
    assert success.calls == [task_id]


def test_recovery_uses_started_completion_markers_without_redispatch(tmp_path: Path) -> None:
    store = _store(tmp_path)
    task_id = _submit(store)
    success = CompleteSuccess(store)
    dispatcher = NeverDispatch()
    runner, invocations, workspaces = _runner(
        store,
        tmp_path,
        success,
        dispatcher=dispatcher,
    )
    workspace = workspaces.allocate(prefix="task")
    invocations.create(task_id, workspace.directory)
    workspace.path_for("stdout.txt").write_bytes(b"done\n")
    workspace.path_for("stderr.txt").write_bytes(b"")
    _publish_started(workspace, task_id)
    _publish_completion(workspace, task_id, True)

    task = store.get(task_id)
    assert task is not None
    runner.recover(task)

    assert dispatcher.calls == 0
    assert store.accumulated_stream(task_id, "stdout") == "done\n"
    assert store.get(task_id).status == "completed"  # type: ignore[union-attr]
    assert invocations.get(task_id) is None
    assert not workspace.directory.exists()


def test_python_failure_keeps_traceback_in_stderr_without_runtime_failure(tmp_path: Path) -> None:
    store = _store(tmp_path)
    task_id = _submit(store)
    runner, invocations, workspaces = _runner(store, tmp_path, CompleteSuccess(store))
    workspace = workspaces.allocate(prefix="task")
    invocations.create(task_id, workspace.directory)
    workspace.path_for("stdout.txt").write_bytes(b"before\n")
    workspace.path_for("stderr.txt").write_bytes(b"Traceback...\nRuntimeError: boom\n")
    _publish_started(workspace, task_id)
    _publish_completion(workspace, task_id, False)

    task = store.get(task_id)
    assert task is not None
    runner.recover(task)

    failed = store.get(task_id)
    assert failed is not None
    assert failed.status == "failed"
    assert failed.runtime_failure_code is None
    assert failed.runtime_failure_message is None
    assert "RuntimeError: boom" in store.accumulated_stream(task_id, "stderr")


def test_runtime_failure_is_structured_and_does_not_fabricate_stderr(tmp_path: Path) -> None:
    store = _store(tmp_path)
    task_id = _submit(store)
    runner, invocations, workspaces = _runner(
        store,
        tmp_path,
        CompleteSuccess(store),
        identity_reader=lambda _pid: ProcessIdentity(4242, "different-incarnation"),
    )
    workspace = workspaces.allocate(prefix="task")
    invocations.create(task_id, workspace.directory)
    workspace.path_for("stdout.txt").write_bytes(b"partial\n")
    workspace.path_for("stderr.txt").write_bytes(b"")
    _publish_started(workspace, task_id)

    task = store.get(task_id)
    assert task is not None
    runner.recover(task)

    failed = store.get(task_id)
    assert failed is not None
    assert failed.status == "failed"
    assert failed.runtime_failure_code == "task_target_changed"
    assert store.accumulated_stream(task_id, "stderr") == ""
    assert store.accumulated_stream(task_id, "stdout") == "partial\n"


def test_recovery_before_started_marker_does_not_replay_when_target_is_gone(tmp_path: Path) -> None:
    store = _store(tmp_path)
    task_id = _submit(store)
    success = CompleteSuccess(store)
    dispatcher = NeverDispatch()
    invocations = TaskInvocationStore(store.database)
    workspaces = TemporaryWorkspaceService(temp_root=tmp_path / "temp")
    workspace = workspaces.allocate(prefix="task")
    invocations.create(task_id, workspace.directory)
    runner = TaskInvocationRunner(
        store,
        invocations,
        workspaces,
        success,
        dispatcher=dispatcher,
        identity_reader=lambda _pid: ProcessIdentity(4242, "different-incarnation"),
        sleep=lambda _seconds: None,
        poll_interval_seconds=0.01,
    )

    task = store.get(task_id)
    assert task is not None
    runner.recover(task)

    failed = store.get(task_id)
    assert failed is not None
    assert failed.status == "failed"
    assert failed.runtime_failure_code == "task_target_changed"
    assert dispatcher.calls == 0

def test_runtime_failure_survives_stream_drain_error(tmp_path: Path) -> None:
    store = _store(tmp_path)
    task_id = _submit(store)
    runner, invocations, workspaces = _runner(store, tmp_path, CompleteSuccess(store))
    workspace = workspaces.allocate(prefix="task")
    invocations.create(task_id, workspace.directory)
    stdout = workspace.path_for("stdout.txt")
    stdout.write_text("partial\n", encoding="utf-8")
    workspace.path_for("stderr.txt").write_text("", encoding="utf-8")
    TaskStreamCollector(invocations).drain(task_id, workspace)
    stdout.unlink()

    task = store.get(task_id)
    assert task is not None
    runner.runtime_failed(
        task,
        BridgeError("task_dispatch_timeout", "Task dispatch timed out."),
    )

    failed = store.get(task_id)
    assert failed is not None
    assert failed.status == "failed"
    assert failed.runtime_failure_code == "task_dispatch_timeout"
    assert invocations.get(task_id) is None
    assert not workspace.directory.exists()


def test_stream_collector_keeps_incomplete_utf8_for_next_chunk(tmp_path: Path) -> None:
    store = _store(tmp_path)
    task_id = _submit(store)
    invocations = TaskInvocationStore(store.database)
    workspaces = TemporaryWorkspaceService(temp_root=tmp_path / "temp")
    workspace = workspaces.allocate(prefix="task")
    invocations.create(task_id, workspace.directory)
    collector = TaskStreamCollector(invocations)
    payload = "AあB".encode("utf-8")
    path = workspace.path_for("stdout.txt")
    path.write_bytes(payload[:2])
    workspace.path_for("stderr.txt").write_bytes(b"")

    collector.drain(task_id, workspace)
    assert store.accumulated_stream(task_id, "stdout") == "A"
    path.write_bytes(payload)
    collector.drain(task_id, workspace, final=True)
    assert store.accumulated_stream(task_id, "stdout") == "AあB"


def test_stream_collector_retries_after_offset_cas_race(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store = _store(tmp_path)
    task_id = _submit(store)
    invocations = TaskInvocationStore(store.database)
    workspaces = TemporaryWorkspaceService(temp_root=tmp_path / "temp")
    workspace = workspaces.allocate(prefix="task")
    invocations.create(task_id, workspace.directory)
    workspace.path_for("stdout.txt").write_bytes(b"abcdef")
    workspace.path_for("stderr.txt").write_bytes(b"")
    collector = TaskStreamCollector(invocations)
    append = invocations.append_transport_chunk
    raced = False

    def append_with_race(
        task_id: str,
        stream: str,
        *,
        expected_offset: int,
        consumed_bytes: int,
        content: str,
    ) -> int:
        nonlocal raced
        if not raced:
            raced = True
            assert expected_offset == 0
            assert consumed_bytes == 6
            assert content == "abcdef"
            append(
                task_id,
                stream,
                expected_offset=0,
                consumed_bytes=3,
                content="abc",
            )
        return append(
            task_id,
            stream,
            expected_offset=expected_offset,
            consumed_bytes=consumed_bytes,
            content=content,
        )

    monkeypatch.setattr(invocations, "append_transport_chunk", append_with_race)
    collector.drain(task_id, workspace, final=True)

    assert store.accumulated_stream(task_id, "stdout") == "abcdef"


def test_houdini_task_runtime_publishes_started_before_source_and_traceback_to_stderr(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from houbridge.houdini.scripts.task import runtime

    monkeypatch.setitem(sys.modules, "hou", types.ModuleType("hou"))
    started = tmp_path / "started.json"
    completion = tmp_path / "completion.json"
    stdout = tmp_path / "stdout.txt"
    stderr = tmp_path / "stderr.txt"
    source = tmp_path / "source.py"
    source.write_text(
        "from pathlib import Path\n"
        f"assert Path({str(started)!r}).is_file()\n"
        "print('before failure', flush=True)\n"
        "raise RuntimeError('boom')\n",
        encoding="utf-8",
    )
    request = tmp_path / "request.json"
    request.write_text(
        json.dumps(
            {
                "task_id": "marker-order-000",
                "source_file": str(source),
                "source_path": str(source),
                "argv": (str(source),),
                "stdout_file": str(stdout),
                "stderr_file": str(stderr),
                "started_marker": str(started),
                "completion_marker": str(completion),
            }
        ),
        encoding="utf-8",
    )

    runtime.run(str(request))

    assert json.loads(started.read_text(encoding="utf-8")) == {
        "version": 1,
        "task_id": "marker-order-000",
    }
    assert json.loads(completion.read_text(encoding="utf-8")) == {
        "version": 1,
        "task_id": "marker-order-000",
        "python_ok": False,
    }
    assert stdout.read_text(encoding="utf-8") == "before failure\n"
    assert "RuntimeError: boom" in stderr.read_text(encoding="utf-8")


def test_houdini_task_runtime_publishes_wrapper_failure_after_python_finished(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from houbridge.houdini.scripts.task import runtime

    monkeypatch.setitem(sys.modules, "hou", types.ModuleType("hou"))
    started = tmp_path / "started.json"
    python_finished = tmp_path / "python-finished.json"
    wrapper_failed = tmp_path / "wrapper-failed.json"
    completion = tmp_path / "completion.json"
    stdout = tmp_path / "stdout.txt"
    stderr = tmp_path / "stderr.txt"
    source = tmp_path / "source.py"
    source.write_text("value = 1\n", encoding="utf-8")
    request = tmp_path / "request.json"
    request.write_text(
        json.dumps(
            {
                "task_id": "wrapper-failure-000",
                "source_file": str(source),
                "source_path": str(source),
                "argv": (str(source),),
                "stdout_file": str(stdout),
                "stderr_file": str(stderr),
                "started_marker": str(started),
                "python_finished_marker": str(python_finished),
                "wrapper_failed_marker": str(wrapper_failed),
                "completion_marker": str(completion),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        runtime,
        "_flush_file",
        lambda _stream: (_ for _ in ()).throw(OSError("simulated fsync failure")),
    )

    with pytest.raises(OSError, match="simulated fsync failure"):
        runtime.run(str(request))

    assert json.loads(started.read_text(encoding="utf-8"))["task_id"] == "wrapper-failure-000"
    assert json.loads(python_finished.read_text(encoding="utf-8")) == {
        "version": 1,
        "task_id": "wrapper-failure-000",
        "python_ok": True,
    }
    assert json.loads(wrapper_failed.read_text(encoding="utf-8")) == {
        "version": 1,
        "task_id": "wrapper-failure-000",
        "detail": "OSError: simulated fsync failure",
    }
    assert not completion.exists()


def test_many_stream_flushes_remain_one_accumulated_logical_stream(tmp_path: Path) -> None:
    store = _store(tmp_path)
    task_id = _submit(store)
    invocations = TaskInvocationStore(store.database)
    workspaces = TemporaryWorkspaceService(temp_root=tmp_path / "temp")
    workspace = workspaces.allocate(prefix="task")
    invocations.create(task_id, workspace.directory)
    stdout = workspace.path_for("stdout.txt")
    stderr = workspace.path_for("stderr.txt")
    stdout.write_bytes(b"")
    stderr.write_bytes(b"")
    collector = TaskStreamCollector(invocations)

    expected = ""
    for index in range(100):
        chunk = f"{index:03d}\n"
        expected += chunk
        with stdout.open("ab") as stream:
            stream.write(chunk.encode("utf-8"))
        collector.drain(task_id, workspace)

    assert store.accumulated_stream(task_id, "stdout") == expected


def test_terminal_task_workspace_left_by_crash_is_cleanup_recoverable(tmp_path: Path) -> None:
    store = _store(tmp_path)
    task_id = _submit(store)
    runner, invocations, workspaces = _runner(store, tmp_path, CompleteSuccess(store))
    workspace = workspaces.allocate(prefix="task")
    invocations.create(task_id, workspace.directory)
    store.mark_running(task_id)
    store.mark_python_failed(task_id)

    runner.cleanup_terminal_workspaces()

    assert invocations.get(task_id) is None
    assert not workspace.directory.exists()


def test_started_python_without_finished_marker_has_no_post_start_timeout(tmp_path: Path) -> None:
    from datetime import datetime, timedelta, timezone

    store = _store(tmp_path)
    task_id = _submit(store, timeout=1.0)
    base = datetime(2026, 9, 11, 8, 0, tzinfo=timezone.utc)
    invocations = TaskInvocationStore(store.database, now=lambda: base)
    workspaces = TemporaryWorkspaceService(temp_root=tmp_path / "temp-running")

    class StopMonitor(Exception):
        pass

    class ExitedHandle:
        def poll(self):
            return 7

        def terminate(self):
            raise AssertionError("started caller Python must not be terminated by dispatch timeout")

    class Dispatcher:
        def start(self, task, script_path):
            workspace = TemporaryWorkspace(script_path.parent)
            workspace.path_for("stdout.txt").write_text("", encoding="utf-8")
            workspace.path_for("stderr.txt").write_text("", encoding="utf-8")
            _publish_started(workspace, task.id)
            return ExitedHandle()

    runner = TaskInvocationRunner(
        store,
        invocations,
        workspaces,
        CompleteSuccess(store),
        dispatcher=Dispatcher(),
        identity_reader=lambda _pid: ProcessIdentity(4242, "process-4242"),
        sleep=lambda _seconds: (_ for _ in ()).throw(StopMonitor()),
        now=lambda: base + timedelta(seconds=20),
        poll_interval_seconds=0.01,
    )
    task = store.get(task_id)
    assert task is not None

    with pytest.raises(StopMonitor):
        runner.run(task)

    running = store.get(task_id)
    assert running is not None
    assert running.status == "running"
    assert running.runtime_failure_code is None


def test_dispatch_timeout_applies_only_before_started_marker(tmp_path: Path) -> None:
    from datetime import datetime, timedelta, timezone

    store = _store(tmp_path)
    task_id = _submit(store, timeout=1.0)
    base = datetime(2026, 9, 11, 8, 0, tzinfo=timezone.utc)
    invocations = TaskInvocationStore(store.database, now=lambda: base)
    workspaces = TemporaryWorkspaceService(temp_root=tmp_path / "temp-timeout")

    class Handle:
        terminated = False

        def poll(self):
            return None

        def terminate(self):
            self.terminated = True

    handle = Handle()

    class Dispatcher:
        def start(self, task, script_path):
            return handle

    runner = TaskInvocationRunner(
        store,
        invocations,
        workspaces,
        CompleteSuccess(store),
        dispatcher=Dispatcher(),
        identity_reader=lambda _pid: ProcessIdentity(4242, "process-4242"),
        sleep=lambda _seconds: None,
        now=lambda: base + timedelta(seconds=2),
        poll_interval_seconds=0.01,
    )
    task = store.get(task_id)
    assert task is not None
    runner.run(task)

    failed = store.get(task_id)
    assert failed is not None
    assert failed.status == "failed"
    assert failed.runtime_failure_code == "task_dispatch_timeout"
    assert handle.terminated is True


def test_preflight_does_not_consume_dispatch_timeout_budget(tmp_path: Path) -> None:
    from datetime import datetime, timedelta, timezone

    store = _store(tmp_path)
    task_id = _submit(store, timeout=5.0, history=True)
    base = datetime(2026, 9, 11, 8, 0, tzinfo=timezone.utc)
    clock = [base]
    invocations = TaskInvocationStore(store.database, now=lambda: clock[0])
    workspaces = TemporaryWorkspaceService(temp_root=tmp_path / "temp-preflight")
    sleep_durations: list[float] = []
    dispatch_timestamps: list[str] = []

    class SlowHistory:
        def prepare(self, _task, _workspace):
            clock[0] += timedelta(seconds=10)
            return None

    class Handle:
        terminated = False

        def poll(self):
            return None

        def terminate(self):
            self.terminated = True

    handle = Handle()

    class Dispatcher:
        def start(self, _task, _script_path):
            state = invocations.get(task_id)
            assert state is not None
            dispatch_timestamps.append(state.dispatch_started_at)
            return handle

    def sleep(seconds: float) -> None:
        sleep_durations.append(seconds)
        clock[0] += timedelta(seconds=seconds)

    runner = TaskInvocationRunner(
        store,
        invocations,
        workspaces,
        CompleteSuccess(store),
        history=SlowHistory(),
        dispatcher=Dispatcher(),
        identity_reader=lambda _pid: ProcessIdentity(4242, "process-4242"),
        sleep=sleep,
        now=lambda: clock[0],
        poll_interval_seconds=1.0,
    )
    task = store.get(task_id)
    assert task is not None

    runner.run(task)

    failed = store.get(task_id)
    assert failed is not None
    assert failed.status == "failed"
    assert failed.runtime_failure_code == "task_dispatch_timeout"
    assert len(sleep_durations) == 5
    assert dispatch_timestamps == [(base + timedelta(seconds=10)).isoformat()]
    assert handle.terminated


def test_recovery_keeps_creation_timestamp_before_dispatch_refresh(
    tmp_path: Path,
) -> None:
    from datetime import datetime, timedelta, timezone

    store = _store(tmp_path)
    task_id = _submit(store, timeout=1.0)
    base = datetime(2026, 9, 11, 8, 0, tzinfo=timezone.utc)
    invocations = TaskInvocationStore(store.database, now=lambda: base)
    workspaces = TemporaryWorkspaceService(temp_root=tmp_path / "temp-creation")
    workspace = workspaces.allocate(prefix="task")
    created = invocations.create(task_id, workspace.directory)
    assert created.dispatch_started_at == base.isoformat()
    dispatcher = NeverDispatch()
    runner = TaskInvocationRunner(
        store,
        invocations,
        workspaces,
        CompleteSuccess(store),
        dispatcher=dispatcher,
        identity_reader=lambda _pid: ProcessIdentity(4242, "process-4242"),
        now=lambda: base + timedelta(seconds=2),
        sleep=lambda _seconds: None,
        poll_interval_seconds=0.01,
    )
    task = store.get(task_id)
    assert task is not None

    runner.recover(task)

    failed = store.get(task_id)
    assert failed is not None
    assert failed.status == "failed"
    assert failed.runtime_failure_code == "task_dispatch_timeout"
    assert dispatcher.calls == 0


def test_dispatch_timestamp_is_captured_after_database_begin_wait(
    tmp_path: Path, monkeypatch
) -> None:
    from contextlib import contextmanager
    from datetime import datetime, timedelta, timezone

    store = _store(tmp_path)
    task_id = _submit(store)
    base = datetime(2026, 9, 11, 8, 0, tzinfo=timezone.utc)
    clock = [base]
    invocations = TaskInvocationStore(store.database, now=lambda: clock[0])
    workspace = TemporaryWorkspaceService(
        temp_root=tmp_path / "temp-begin-wait"
    ).allocate(prefix="task")
    invocations.create(task_id, workspace.directory)
    original_connect = invocations._connect

    class AdvancingConnection:
        def __init__(self, connection) -> None:
            self.connection = connection

        def execute(self, sql, parameters=()):
            if sql == "BEGIN IMMEDIATE":
                clock[0] += timedelta(seconds=3)
            return self.connection.execute(sql, parameters)

    @contextmanager
    def delayed_connect():
        with original_connect() as connection:
            yield AdvancingConnection(connection)

    monkeypatch.setattr(invocations, "_connect", delayed_connect)

    refreshed = invocations.mark_dispatch_started(task_id)

    assert refreshed.dispatch_started_at == (base + timedelta(seconds=3)).isoformat()


def test_dispatch_timestamp_storage_error_fails_closed_before_dispatch(
    tmp_path: Path, monkeypatch
) -> None:
    import sqlite3
    from contextlib import contextmanager

    store = _store(tmp_path)
    task_id = _submit(store)
    invocations = TaskInvocationStore(store.database)

    class CapturingWorkspaces(TemporaryWorkspaceService):
        workspace: TemporaryWorkspace | None = None

        def allocate(self, *, prefix: str = "invocation") -> TemporaryWorkspace:
            self.workspace = super().allocate(prefix=prefix)
            return self.workspace

    workspaces = CapturingWorkspaces(temp_root=tmp_path / "temp-store-failure")
    original_connect = invocations._connect
    fail_update = [True]

    class FailingConnection:
        def __init__(self, connection) -> None:
            self.connection = connection

        def execute(self, sql, parameters=()):
            if sql.startswith("UPDATE task_invocations") and fail_update[0]:
                fail_update[0] = False
                raise sqlite3.OperationalError("simulated timestamp write failure")
            return self.connection.execute(sql, parameters)

    @contextmanager
    def fail_once_on_update():
        with original_connect() as connection:
            yield FailingConnection(connection)

    monkeypatch.setattr(invocations, "_connect", fail_once_on_update)
    dispatcher = NeverDispatch()
    runner = TaskInvocationRunner(
        store,
        invocations,
        workspaces,
        CompleteSuccess(store),
        dispatcher=dispatcher,
        identity_reader=lambda _pid: ProcessIdentity(4242, "process-4242"),
    )
    task = store.get(task_id)
    assert task is not None

    runner.run(task)

    failed = store.get(task_id)
    assert failed is not None
    assert failed.status == "failed"
    assert failed.runtime_failure_code == "task_store_failed"
    assert dispatcher.calls == 0
    assert workspaces.workspace is not None
    assert not workspaces.workspace.directory.exists()
    assert invocations.get(task_id) is None
