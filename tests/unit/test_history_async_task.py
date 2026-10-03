from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from houbridge.errors import BridgeError
from houbridge.history.service import HistoryStorageService
from houbridge.houdini.scripts.task.runtime import run as run_task_script
from houbridge.paths import GlobalDataPaths
from houbridge.process_coordination import ProcessIdentity
from houbridge.semantic_id import SemanticBase
from houbridge.task.history import AsyncTaskHistory
from houbridge.task.invocation_store import TaskInvocationStore
from houbridge.task.models import FrozenDispatchContext, TaskSubmission
from houbridge.task.runner import TaskInvocationRunner
from houbridge.task.store import TaskStore
from houbridge.task.workspace import stage_task_request
from houbridge.temporary_workspace import TemporaryWorkspaceService


class FixedSemanticGenerator:
    def generate(self, _text: str, *, fallback_stem: str) -> SemanticBase:
        assert fallback_stem == "task-unknown"
        return SemanticBase(prefix="history-async-work", tags=("history", "async", "work"))


class FakeEmbeddingProvider:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[tuple[str, tuple[str, ...]]] = []

    def encode(self, texts, profile: str) -> np.ndarray:
        values = tuple(texts)
        self.calls.append((profile, values))
        if self.fail:
            raise RuntimeError("embedding unavailable")
        return np.asarray([[1.0, 2.0, 3.0] for _ in values], dtype=np.float32)


class NeverResourceStore:
    def put_bytes(self, _payload: bytes):
        raise AssertionError("empty Action Changes must not create a Resource")


class CompletingSuccess:
    def __init__(self, store: TaskStore) -> None:
        self._store = store

    def finalize_success(self, task) -> None:
        self._store.mark_completed(task.id)


class NeverDispatch:
    def __init__(self) -> None:
        self.calls = 0

    def start(self, _task, _script_path):
        self.calls += 1
        raise AssertionError("History preflight failure must prevent dispatch")


class AcceptTarget:
    def validate(self, _task) -> None:
        return None


class FailingHistoryFinalization:
    def prepare(self, _task, _workspace):
        raise AssertionError("recovery must not replay History preflight")

    def finalize(self, _task, _workspace, *, python_ok: bool) -> None:
        raise RuntimeError("history database unavailable")


def _submission(
    *,
    source: str = "print('hello')\n",
    purpose: str | None = "build preview geometry",
    history_enabled: bool = True,
    profile: str = "profile-a",
) -> TaskSubmission:
    return TaskSubmission(
        source=source,
        file_path="/workspace/task.py",
        argv=("/workspace/task.py", "--quality", "high"),
        purpose=purpose,
        origin_cwd="/workspace",
        dispatch=FrozenDispatchContext(
            session=1,
            port=1714,
            pid=4242,
            process_start_identity="process-4242",
            transport_executable="hcommand",
            transport_timeout_seconds=5,
            transport_environment={},
            lock_timeout_seconds=5,
        ),
        history_enabled=history_enabled,
        history_code_profile=profile,
    )


def _store(tmp_path: Path) -> TaskStore:
    return TaskStore(
        tmp_path / "data" / "tasks.db",
        semantic_generator=FixedSemanticGenerator(),
    )


def _history(
    tmp_path: Path,
    provider: FakeEmbeddingProvider,
) -> tuple[AsyncTaskHistory, HistoryStorageService]:
    paths = GlobalDataPaths.from_data_dir(tmp_path / "data")
    storage = HistoryStorageService(paths, embedding_provider=provider)
    history = AsyncTaskHistory(
        storage,
        resource_store=NeverResourceStore(),  # type: ignore[arg-type]
    )
    return history, storage


def test_submission_freezes_requested_history_profile_in_tasks_db(tmp_path: Path) -> None:
    store = _store(tmp_path)

    task = store.submit(_submission(profile="profile-submit-a"))

    restored = store.get(task.id)
    assert restored is not None
    assert restored.history_enabled is True
    assert restored.history_code_profile == "profile-submit-a"
    with sqlite3.connect(store.database) as connection:
        row = connection.execute(
            "SELECT history_code_profile FROM tasks WHERE id = ?",
            (task.id,),
        ).fetchone()
    assert row == ("profile-submit-a",)


def test_existing_session_profile_overrides_frozen_requested_profile_at_start(tmp_path: Path) -> None:
    provider = FakeEmbeddingProvider()
    history, storage = _history(tmp_path, provider)
    identity = ProcessIdentity(4242, "process-4242")
    pinned = storage.for_recording(
        identity,
        enabled=True,
        requested_code_profile="profile-session-pinned",
    )
    assert pinned is not None
    store = _store(tmp_path)
    task = store.submit(_submission(profile="profile-submission"))
    workspace = TemporaryWorkspaceService(temp_root=tmp_path / "temp").allocate(prefix="task")

    preparation = history.prepare(task, workspace)

    assert preparation is not None
    assert preparation.storage.code_profile == "profile-session-pinned"
    assert provider.calls == [("profile-session-pinned", (task.source,))]


def test_enabled_history_preflight_failure_marks_task_failed_without_dispatch(tmp_path: Path) -> None:
    store = _store(tmp_path)
    task = store.submit(_submission())
    history, _storage = _history(tmp_path, FakeEmbeddingProvider(fail=True))
    dispatcher = NeverDispatch()
    invocations = TaskInvocationStore(store.database)
    runner = TaskInvocationRunner(
        store,
        invocations,
        TemporaryWorkspaceService(temp_root=tmp_path / "temp"),
        CompletingSuccess(store),
        history=history,
        dispatcher=dispatcher,
        target_validator=AcceptTarget(),
        identity_reader=lambda _pid: task.dispatch.process_identity,
        sleep=lambda _seconds: None,
    )

    runner.run(task)

    failed = store.get(task.id)
    assert failed is not None
    assert failed.status == "failed"
    assert failed.runtime_failure_code == "history_preflight_failed"
    assert dispatcher.calls == 0
    assert invocations.get(task.id) is None


def test_async_history_finalization_preserves_frozen_metadata_and_is_idempotent(tmp_path: Path) -> None:
    provider = FakeEmbeddingProvider()
    history, storage = _history(tmp_path, provider)
    store = _store(tmp_path)
    task = store.submit(_submission(source="raise RuntimeError('boom')\n"))
    workspace = TemporaryWorkspaceService(temp_root=tmp_path / "temp").allocate(prefix="task")
    preparation = history.prepare(task, workspace)
    assert preparation is not None
    preparation.capture_path.write_text(
        json.dumps(
            {
                "time": "2026-09-11T10:20:30+00:00",
                "scene_replaced": False,
                "changes": [],
            },
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )

    history.finalize(task, workspace, python_ok=False)
    # Replacement runtime may observe the same completion marker after a host
    # crash. Re-finalization must not create a second Action History entry.
    history.finalize(task, workspace, python_ok=False)

    database = storage.database_for(task.dispatch.process_identity)
    with sqlite3.connect(database) as connection:
        connection.row_factory = sqlite3.Row
        entries = connection.execute("SELECT * FROM history_entries ORDER BY id").fetchall()
        keys = connection.execute(
            "SELECT execution_key, entry_id FROM history_execution_keys"
        ).fetchall()
    assert len(entries) == 1
    entry = entries[0]
    assert entry["status"] == "failed"
    assert entry["cwd"] == str(Path("/workspace").resolve())
    assert entry["file"] == str(Path("/workspace/task.py").resolve())
    assert json.loads(entry["args_json"]) == ["--quality", "high"]
    assert entry["purpose"] == "build preview geometry"
    assert entry["source_hash"] == hashlib.sha256(task.source.encode("utf-8")).hexdigest()  # type: ignore[union-attr]
    assert [(row["execution_key"], row["entry_id"]) for row in keys] == [
        (f"task:{task.id}:{workspace.directory.resolve()}", entry["id"])
    ]


def test_task_reset_reused_id_records_distinct_history_entry(tmp_path: Path) -> None:
    provider = FakeEmbeddingProvider()
    history, storage = _history(tmp_path, provider)
    store = _store(tmp_path)
    workspaces = TemporaryWorkspaceService(temp_root=tmp_path / "temp")

    first = store.submit(_submission())
    first_workspace = workspaces.allocate(prefix="task")
    first_preparation = history.prepare(first, first_workspace)
    assert first_preparation is not None
    first_preparation.capture_path.write_text(
        json.dumps(
            {
                "time": "2026-09-11T10:20:30+00:00",
                "scene_replaced": False,
                "changes": [],
            },
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    history.finalize(first, first_workspace, python_ok=True)
    store.mark_runtime_failed(first.id, code="test_terminal", message="terminal")
    store.reset()

    second = store.submit(_submission())
    assert second.id == first.id
    second_workspace = workspaces.allocate(prefix="task")
    second_preparation = history.prepare(second, second_workspace)
    assert second_preparation is not None
    second_preparation.capture_path.write_text(
        json.dumps(
            {
                "time": "2026-09-11T10:21:30+00:00",
                "scene_replaced": False,
                "changes": [],
            },
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    history.finalize(second, second_workspace, python_ok=True)

    database = storage.database_for(second.dispatch.process_identity)
    with sqlite3.connect(database) as connection:
        entries = connection.execute("SELECT id FROM history_entries ORDER BY id").fetchall()
        keys = connection.execute(
            "SELECT execution_key, entry_id FROM history_execution_keys ORDER BY entry_id"
        ).fetchall()
    assert entries == [(1,), (2,)]
    assert keys == [
        (f"task:{first.id}:{first_workspace.directory.resolve()}", 1),
        (f"task:{second.id}:{second_workspace.directory.resolve()}", 2),
    ]


def test_task_houdini_history_baseline_failure_precedes_started_marker_and_caller_python(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "hou", types.ModuleType("hou"))
    store = _store(tmp_path)
    task = store.submit(_submission())
    marker = tmp_path / "caller-ran.txt"
    task_with_marker = store.get(task.id)
    assert task_with_marker is not None
    # Use a fresh Task with source that would leave an observable marker.
    store.mark_runtime_failed(task.id, code="replace", message="replace")
    task_with_marker = store.submit(
        _submission(
            source=(
                "from pathlib import Path\n"
                f"Path({str(marker)!r}).write_text('ran', encoding='utf-8')\n"
            )
        )
    )
    workspace = TemporaryWorkspaceService(temp_root=tmp_path / "temp").allocate(prefix="task")
    history_runtime = workspace.path_for("failing-history-runtime.py")
    history_runtime.write_text(
        "def prepare(_request):\n    raise RuntimeError('baseline failed')\n"
        "def finalize(_context):\n    raise AssertionError('unreachable')\n",
        encoding="utf-8",
    )
    history_request = workspace.path_for("history-request.json")
    history_request.write_text("{}", encoding="utf-8")
    preparation = SimpleNamespace(runtime_script=history_runtime, request_path=history_request)
    request_path = stage_task_request(workspace, task_with_marker, history=preparation)  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="baseline failed"):
        run_task_script(str(request_path))

    assert not marker.exists()
    assert not workspace.path_for("started.json").exists()
    assert not workspace.path_for("completion.json").exists()


def test_history_finalization_failure_after_started_success_does_not_change_task_outcome_or_replay(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    task = store.submit(_submission())
    invocations = TaskInvocationStore(store.database)
    workspaces = TemporaryWorkspaceService(temp_root=tmp_path / "temp")
    workspace = workspaces.allocate(prefix="task")
    invocations.create(task.id, workspace.directory)
    workspace.path_for("stdout.txt").write_text("done\n", encoding="utf-8")
    workspace.path_for("stderr.txt").write_text("", encoding="utf-8")
    workspace.publish_marker(
        "started.json",
        json.dumps({"version": 1, "task_id": task.id}, separators=(",", ":")).encode(),
    )
    workspace.publish_marker(
        "completion.json",
        json.dumps(
            {"version": 1, "task_id": task.id, "python_ok": True},
            separators=(",", ":"),
        ).encode(),
    )
    dispatcher = NeverDispatch()
    runner = TaskInvocationRunner(
        store,
        invocations,
        workspaces,
        CompletingSuccess(store),
        history=FailingHistoryFinalization(),  # type: ignore[arg-type]
        dispatcher=dispatcher,
        target_validator=AcceptTarget(),
        identity_reader=lambda _pid: task.dispatch.process_identity,
        sleep=lambda _seconds: None,
    )

    runner.recover(task)

    terminal = store.get(task.id)
    assert terminal is not None
    assert terminal.status == "completed"
    assert terminal.runtime_failure_code is None
    assert dispatcher.calls == 0


def test_stream_flush_failure_closes_houdini_history_recorder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from houbridge.history.locking import history_database_lock_path
    from houbridge.houdini.scripts.history import execution as history_runtime
    from houbridge.houdini.scripts.task import runtime as task_runtime
    from test_history_sync_execution import FakeNode, _install_fake_hou

    monkeypatch.delitem(
        sys.modules, "_houbridge_history_scene_lifecycle_v1", raising=False
    )
    root = FakeNode()
    _install_fake_hou(monkeypatch, root=root)
    store = _store(tmp_path)
    task = store.submit(_submission(source="result = 1\n"))
    workspace = TemporaryWorkspaceService(temp_root=tmp_path / "temp").allocate(
        prefix="task"
    )
    history_request = workspace.path_for("history-request.json")
    database = tmp_path / "history.db"
    history_request.write_text(
        json.dumps(
            {
                "database_path": str(database),
                "database_lock_path": str(history_database_lock_path(database)),
                "capture_file": str(workspace.path_for("history-capture.json")),
            }
        ),
        encoding="utf-8",
    )
    preparation = SimpleNamespace(
        runtime_script=Path(history_runtime.__file__), request_path=history_request
    )
    request_path = stage_task_request(workspace, task, history=preparation)
    monkeypatch.setattr(
        task_runtime,
        "_flush_file",
        lambda _stream: (_ for _ in ()).throw(OSError("stream flush failed")),
    )

    with pytest.raises(OSError, match="stream flush failed"):
        run_task_script(str(request_path))

    assert root._callbacks == []
    assert workspace.path_for("started.json").exists()
    assert not workspace.path_for("completion.json").exists()


@pytest.mark.parametrize(
    ("failure_point", "caller_runs"),
    [
        ("stdout_open", False),
        ("started_marker", False),
        ("completion_marker", True),
    ],
)
def test_async_artifact_failures_close_history_recorder(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_point: str,
    caller_runs: bool,
) -> None:
    from houbridge.history.locking import history_database_lock_path
    from houbridge.houdini.scripts.history import execution as history_runtime
    from houbridge.houdini.scripts.task import runtime as task_runtime
    from test_history_sync_execution import FakeNode, _install_fake_hou

    monkeypatch.delitem(
        sys.modules, "_houbridge_history_scene_lifecycle_v1", raising=False
    )
    root = FakeNode()
    _install_fake_hou(monkeypatch, root=root)
    store = _store(tmp_path)
    caller_marker = tmp_path / "caller-ran.txt"
    task = store.submit(
        _submission(
            source=(
                "from pathlib import Path\n"
                f"Path({str(caller_marker)!r}).write_text('ran')\n"
            )
        )
    )
    workspace = TemporaryWorkspaceService(temp_root=tmp_path / "temp").allocate(
        prefix="task"
    )
    history_request = workspace.path_for("history-request.json")
    database = tmp_path / "history.db"
    history_request.write_text(
        json.dumps(
            {
                "database_path": str(database),
                "database_lock_path": str(history_database_lock_path(database)),
                "capture_file": str(workspace.path_for("history-capture.json")),
            }
        ),
        encoding="utf-8",
    )
    preparation = SimpleNamespace(
        runtime_script=Path(history_runtime.__file__), request_path=history_request
    )
    request_path = stage_task_request(workspace, task, history=preparation)
    request = json.loads(request_path.read_text(encoding="utf-8"))
    failure = OSError(f"injected {failure_point}")

    if failure_point == "stdout_open":
        original_open = Path.open
        stdout_path = Path(request["stdout_file"])

        def fail_stdout_open(path, *args, **kwargs):
            if path == stdout_path:
                raise failure
            return original_open(path, *args, **kwargs)

        monkeypatch.setattr(Path, "open", fail_stdout_open)
    else:
        marker_key = (
            "started_marker"
            if failure_point == "started_marker"
            else "completion_marker"
        )
        marker_path = Path(request[marker_key])
        atomic_write = task_runtime._atomic_write_json

        def fail_marker(path, payload):
            if path == marker_path:
                raise failure
            atomic_write(path, payload)

        monkeypatch.setattr(task_runtime, "_atomic_write_json", fail_marker)

    with pytest.raises(OSError, match=f"injected {failure_point}"):
        run_task_script(str(request_path))

    assert root._callbacks == []
    assert caller_marker.exists() is caller_runs
    assert workspace.path_for("started.json").exists() is (
        failure_point != "started_marker" and failure_point != "stdout_open"
    )
    assert not workspace.path_for("completion.json").exists()
