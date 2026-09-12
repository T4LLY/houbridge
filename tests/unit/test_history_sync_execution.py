from __future__ import annotations

import hashlib
import json
import runpy
import sqlite3
import sys
import types
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from houbridge.errors import BridgeError
from houbridge.execution.models import ExecutionInvocation
from houbridge.execution.runtime import ExecutionRuntime
from houbridge.execution.workspace import stage_invocation
from houbridge.history.execution import SynchronousExecutionHistory
from houbridge.history.service import HistoryStorageService
from houbridge.houdini.scripts.execution.runtime import run as run_execution_script
from houbridge.houdini.transport import HoudiniTarget, TransportResult
from houbridge.paths import GlobalDataPaths
from houbridge.process_coordination import ProcessIdentity
from houbridge.session.probe import SessionProbeResult
from houbridge.session.registry import SessionRecord
from houbridge.session.resolver import ResolvedSession
from houbridge.temporary_workspace import TemporaryWorkspaceService


LIFECYCLE_STATE = "_houbridge_history_scene_lifecycle_v1"


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


class RecordingLock:
    @contextmanager
    def acquire(self, _identity, *, timeout_seconds=None):
        yield


class InProcessTransport:
    def __init__(self) -> None:
        self.calls = 0

    def execute_script(self, _target: HoudiniTarget, script_path: Path) -> TransportResult:
        self.calls += 1
        runpy.run_path(str(script_path))
        return TransportResult("", "", 0)


class NeverTransport:
    def __init__(self) -> None:
        self.calls = 0

    def execute_script(self, _target: HoudiniTarget, _script_path: Path) -> TransportResult:
        self.calls += 1
        raise AssertionError("caller Python must not be dispatched")


class _NodeType:
    def name(self) -> str:
        return "obj"


class FakeNode:
    def __init__(self) -> None:
        self._callbacks: list[tuple[tuple[object, ...], object]] = []

    def sessionId(self) -> int:
        return 1

    def path(self) -> str:
        return "/"

    def type(self) -> _NodeType:
        return _NodeType()

    def parms(self) -> list[object]:
        return []

    def inputConnections(self) -> list[object]:
        return []

    def allSubChildren(self) -> tuple[object, ...]:
        return ()

    def addEventCallback(self, events, callback) -> None:
        self._callbacks.append((events, callback))

    def removeEventCallback(self, events, callback) -> None:
        try:
            self._callbacks.remove((events, callback))
        except ValueError:
            pass

    def isBypassed(self) -> bool:
        return False

    def isDisplayFlagSet(self) -> bool:
        return False

    def isRenderFlagSet(self) -> bool:
        return False

    def isTemplateFlagSet(self) -> bool:
        return False

    def isSelectableTemplateFlagSet(self) -> bool:
        return False


class FakeHipFile:
    def __init__(self) -> None:
        self.callbacks: list[object] = []

    def addEventCallback(self, callback) -> None:
        self.callbacks.append(callback)

    def emit(self, event_type) -> None:
        for callback in tuple(self.callbacks):
            callback(event_type)


@pytest.fixture(autouse=True)
def _clear_lifecycle_state(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delitem(sys.modules, LIFECYCLE_STATE, raising=False)


def _install_fake_hou(monkeypatch: pytest.MonkeyPatch, *, root: FakeNode | None = None):
    node_events = SimpleNamespace(
        ChildCreated=object(),
        ChildDeleted=object(),
        BeingDeleted=object(),
        NameChanged=object(),
        ParmTupleChanged=object(),
        InputRewired=object(),
        FlagChanged=object(),
    )
    hip_events = SimpleNamespace(
        AfterLoad=object(),
        AfterClear=object(),
        AfterMerge=object(),
        AfterSave=object(),
    )
    hip_file = FakeHipFile()
    hou = types.ModuleType("hou")
    hou.nodeEventType = node_events
    hou.hipFileEventType = hip_events
    hou.hipFile = hip_file
    hou.node = lambda path: root if path == "/" else None
    hou.nodeBySessionId = lambda session_id: root if root is not None and session_id == 1 else None
    monkeypatch.setitem(sys.modules, "hou", hou)
    return hou


def _resolved_session() -> ResolvedSession:
    record = SessionRecord(1, 49152, 1001, "start-a")
    return ResolvedSession(
        record=record,
        identity=ProcessIdentity(1001, "start-a"),
        probe=SessionProbeResult(
            pid=1001,
            version="22.0.1",
            license="Commercial",
            file=None,
            headless=False,
            open_ports=(49152,),
        ),
    )


def _invocation(tmp_path: Path, source: str, *, purpose: str | None = "build preview"):
    source_path = tmp_path / "tool.py"
    return ExecutionInvocation(
        source=source,
        source_path=str(source_path),
        argv=(str(source_path), "--quality", "high"),
        purpose=purpose,
        origin_cwd=str(tmp_path.resolve()),
    )


def _history_runtime(
    tmp_path: Path,
    provider: FakeEmbeddingProvider,
    transport,
) -> tuple[ExecutionRuntime, HistoryStorageService]:
    paths = GlobalDataPaths.from_data_dir(tmp_path / "data")
    storage = HistoryStorageService(paths, embedding_provider=provider)
    history = SynchronousExecutionHistory(
        storage,
        requested_code_profile="profile-a",
        resource_store_factory=lambda: NeverResourceStore(),  # type: ignore[arg-type]
    )
    runtime = ExecutionRuntime(
        transport=transport,  # type: ignore[arg-type]
        workspaces=TemporaryWorkspaceService(temp_root=tmp_path / "temp"),
        execution_lock=RecordingLock(),  # type: ignore[arg-type]
        lock_timeout_seconds=1,
        history=history,
    )
    return runtime, storage


@pytest.mark.parametrize(
    ("source", "expected_ok", "expected_status"),
    [
        ("result = 7\n", True, "completed"),
        ("raise RuntimeError('boom')\n", False, "failed"),
    ],
)
def test_sync_started_execution_commits_one_minimal_history_entry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    source: str,
    expected_ok: bool,
    expected_status: str,
) -> None:
    _install_fake_hou(monkeypatch, root=FakeNode())
    provider = FakeEmbeddingProvider()
    transport = InProcessTransport()
    runtime, storage = _history_runtime(tmp_path, provider, transport)
    invocation = _invocation(tmp_path, source)

    outcome = runtime.execute(_resolved_session(), invocation)

    assert outcome.python_ok is expected_ok
    assert transport.calls == 1
    database = storage.database_for(_resolved_session().identity)
    with sqlite3.connect(database) as connection:
        connection.row_factory = sqlite3.Row
        entries = connection.execute("SELECT * FROM history_entries ORDER BY id").fetchall()
        changes = connection.execute("SELECT * FROM history_changes").fetchall()
    assert len(entries) == 1
    entry = entries[0]
    assert entry["id"] == 1
    assert entry["status"] == expected_status
    assert entry["cwd"] == str(tmp_path.resolve())
    assert entry["file"] == str((tmp_path / "tool.py").resolve())
    assert json.loads(entry["args_json"]) == ["--quality", "high"]
    assert entry["purpose"] == "build preview"
    assert entry["source_hash"] == hashlib.sha256(source.encode("utf-8")).hexdigest()
    assert entries[0]["time"]
    assert changes == []
    assert provider.calls == [("profile-a", (source,))]
    assert source.encode("utf-8") not in database.read_bytes()


def test_source_embedding_preflight_failure_prevents_dispatch(
    tmp_path: Path,
) -> None:
    provider = FakeEmbeddingProvider(fail=True)
    transport = NeverTransport()
    runtime, storage = _history_runtime(tmp_path, provider, transport)

    with pytest.raises(BridgeError) as caught:
        runtime.execute(_resolved_session(), _invocation(tmp_path, "result = 1\n"))

    assert caught.value.code == "history_preflight_failed"
    assert transport.calls == 0
    database = storage.database_for(_resolved_session().identity)
    with sqlite3.connect(database) as connection:
        count = connection.execute("SELECT COUNT(*) FROM history_entries").fetchone()[0]
    assert count == 0


def test_action_baseline_failure_occurs_before_caller_python(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_hou(monkeypatch, root=None)
    marker = tmp_path / "caller-started.txt"
    database = tmp_path / "history.db"
    workspace = TemporaryWorkspaceService(temp_root=tmp_path / "temp").allocate(prefix="exec")
    history_request = workspace.path_for("history-request.json")
    capture = workspace.path_for("history-capture.json")
    history_request.write_text(
        json.dumps({"database_path": str(database), "capture_file": str(capture)}),
        encoding="utf-8",
    )
    from houbridge.houdini.scripts.history import execution as history_runtime

    preparation = SimpleNamespace(
        runtime_script=Path(history_runtime.__file__),
        request_path=history_request,
    )
    invocation = ExecutionInvocation(
        source=f"from pathlib import Path\nPath({str(marker)!r}).write_text('started')\n",
        source_path=str(tmp_path / "tool.py"),
        argv=(str(tmp_path / "tool.py"),),
        purpose=None,
        origin_cwd=str(tmp_path),
    )
    request = stage_invocation(workspace, invocation, history=preparation)

    with pytest.raises(RuntimeError, match="root node is unavailable"):
        run_execution_script(str(request))

    assert not marker.exists()
    assert not workspace.path_for("execution.json").exists()


def test_scene_replacement_discards_pending_history_entry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hou = _install_fake_hou(monkeypatch, root=FakeNode())
    provider = FakeEmbeddingProvider()
    transport = InProcessTransport()
    runtime, storage = _history_runtime(tmp_path, provider, transport)
    source = "hou.hipFile.emit(hou.hipFileEventType.AfterClear)\nresult = 1\n"

    outcome = runtime.execute(_resolved_session(), _invocation(tmp_path, source))

    assert outcome.python_ok is True
    assert transport.calls == 1
    assert hou.hipFile.callbacks
    assert not storage.database_for(_resolved_session().identity).exists()


def test_history_finalization_failure_does_not_replay_or_redefine_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_hou(monkeypatch, root=FakeNode())

    class Preparation:
        runtime_script = Path(__file__)  # not used by custom stage request below
        request_path = Path(__file__)

    class FailingHistory:
        def __init__(self) -> None:
            self.finalize_calls = 0

        def prepare(self, invocation, session, workspace):
            # No physical History runtime is needed for this ordering test.
            from houbridge.houdini.scripts.history import execution as history_runtime

            request_path = workspace.path_for("history-request.json")
            request_path.write_text(
                json.dumps(
                    {
                        "database_path": str(tmp_path / "history.db"),
                        "capture_file": str(workspace.path_for("history-capture.json")),
                    }
                ),
                encoding="utf-8",
            )
            return SimpleNamespace(
                runtime_script=Path(history_runtime.__file__),
                request_path=request_path,
            )

        def finalize(self, preparation, invocation, session, outcome, workspace):
            self.finalize_calls += 1
            raise RuntimeError("commit failed")

    history = FailingHistory()
    transport = InProcessTransport()
    runtime = ExecutionRuntime(
        transport=transport,  # type: ignore[arg-type]
        workspaces=TemporaryWorkspaceService(temp_root=tmp_path / "temp"),
        execution_lock=RecordingLock(),  # type: ignore[arg-type]
        lock_timeout_seconds=1,
        history=history,  # type: ignore[arg-type]
    )

    outcome = runtime.execute(_resolved_session(), _invocation(tmp_path, "result = 1\n"))

    assert outcome.python_ok is True
    assert transport.calls == 1
    assert history.finalize_calls == 1

def test_history_disabled_runs_without_history_storage_or_embedding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_hou(monkeypatch, root=FakeNode())
    transport = InProcessTransport()
    runtime = ExecutionRuntime(
        transport=transport,  # type: ignore[arg-type]
        workspaces=TemporaryWorkspaceService(temp_root=tmp_path / "temp"),
        execution_lock=RecordingLock(),  # type: ignore[arg-type]
        lock_timeout_seconds=1,
        history=None,
    )

    outcome = runtime.execute(_resolved_session(), _invocation(tmp_path, "result = 1\n"))

    assert outcome.python_ok is True
    assert transport.calls == 1
    assert not (tmp_path / "data" / "history").exists()
