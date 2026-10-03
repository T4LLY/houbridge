from __future__ import annotations

import os
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

from houbridge.errors import BridgeError
from houbridge.execution.models import ExecutionInvocation
from houbridge.execution.runtime import ExecutionRuntime
from houbridge.houdini.transport import HoudiniTarget, TransportResult
from houbridge.process_coordination import ProcessIdentity
from houbridge.session.probe import SessionProbeResult
from houbridge.session.registry import SessionRecord
from houbridge.session.resolver import ResolvedSession, SessionResolver
from houbridge.temporary_workspace import TemporaryWorkspaceService


class RecordingLock:
    def __init__(self) -> None:
        self.active = False
        self.identities: list[ProcessIdentity] = []
        self.timeouts: list[float | None] = []

    @contextmanager
    def acquire(self, identity: ProcessIdentity, *, timeout_seconds: float | None = None):
        self.identities.append(identity)
        self.timeouts.append(timeout_seconds)
        self.active = True
        try:
            yield
        finally:
            self.active = False


class LocalPythonTransport:
    def __init__(self, fake_hou_root: Path, lock: RecordingLock) -> None:
        self.fake_hou_root = fake_hou_root
        self.lock = lock
        self.calls: list[tuple[HoudiniTarget, Path]] = []

    def execute_script(self, target: HoudiniTarget, script_path: Path) -> TransportResult:
        assert self.lock.active is True
        self.calls.append((target, script_path))
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(self.fake_hou_root)
        completed = subprocess.run(
            [sys.executable, str(script_path)],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=environment,
        )
        if completed.returncode != 0:
            raise AssertionError(completed.stderr)
        return TransportResult(completed.stdout, completed.stderr, completed.returncode)


class TimeoutAfterScriptTransport(LocalPythonTransport):
    def execute_script(self, target: HoudiniTarget, script_path: Path) -> TransportResult:
        super().execute_script(target, script_path)
        raise BridgeError("hcommand_timeout", "transport timed out after caller completion")


class FailingTransport:
    def execute_script(self, target: HoudiniTarget, script_path: Path) -> TransportResult:
        raise BridgeError("houdini_transport_failed", "transport failed")


def _resolved_session() -> ResolvedSession:
    record = SessionRecord(
        session=1,
        port=49152,
        pid=1001,
        process_start_identity="start-a",
    )
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


def _resolver(identity_reader=None, *, identity: ProcessIdentity | None = None):
    current = identity or ProcessIdentity(1001, "start-a")

    class Probe:
        def inspect(self, port: int) -> SessionProbeResult:
            return SessionProbeResult(
                pid=current.pid,
                version="22.0.1",
                license="Commercial",
                file=None,
                headless=False,
                open_ports=(port,),
            )

    return SessionResolver(
        None,  # type: ignore[arg-type]  # resolve_record does not consult registry.
        Probe(),  # type: ignore[arg-type]
        identity_reader=identity_reader or (lambda _pid: current),
    )


def _invocation(source: str) -> ExecutionInvocation:
    return ExecutionInvocation(
        source=source,
        source_path="caller.py",
        argv=("caller.py", "arg"),
        purpose="test purpose",
        origin_cwd="C:/caller",
    )


def test_execution_runtime_stages_locks_dispatches_collects_and_cleans(
    tmp_path: Path,
) -> None:
    fake_hou_root = tmp_path / "fake"
    fake_hou_root.mkdir()
    (fake_hou_root / "hou.py").write_text("VALUE = 7\n", encoding="utf-8")
    workspaces = TemporaryWorkspaceService(temp_root=tmp_path / "temp")
    lock = RecordingLock()
    transport = LocalPythonTransport(fake_hou_root, lock)
    runtime = ExecutionRuntime(
        transport=transport,  # type: ignore[arg-type]
        workspaces=workspaces,
        execution_lock=lock,  # type: ignore[arg-type]
        resolver=_resolver(),
        lock_timeout_seconds=12.5,
    )

    outcome = runtime.execute(
        _resolved_session(),
        _invocation("print('hello')\nresult = {'value': hou.VALUE}\n"),
    )

    assert outcome.python_ok is True
    assert outcome.stdout == "hello\n"
    assert outcome.stderr == ""
    assert outcome.traceback is None
    assert outcome.result is not None
    assert outcome.result.inline_value() == {"value": 7}
    assert lock.identities == [ProcessIdentity(1001, "start-a")]
    assert lock.timeouts == [12.5]
    assert transport.calls[0][0] == HoudiniTarget("127.0.0.1", 49152)
    assert list(workspaces.root.iterdir()) == []


def test_runtime_rejects_replaced_pid_after_lock_wait_and_releases_workspace(
    tmp_path: Path,
) -> None:
    session = _resolved_session()
    current_identity = [session.identity]
    workspaces = TemporaryWorkspaceService(temp_root=tmp_path / "temp")

    class RebindingLock(RecordingLock):
        @contextmanager
        def acquire(self, identity, *, timeout_seconds=None):
            self.identities.append(identity)
            self.timeouts.append(timeout_seconds)
            self.active = True
            current_identity[0] = ProcessIdentity(2002, "replacement")
            try:
                yield
            finally:
                self.active = False

    class NoDispatch:
        calls = 0

        def execute_script(self, target, script_path):
            self.calls += 1
            raise AssertionError("stale Session must not dispatch")

    lock = RebindingLock()
    transport = NoDispatch()
    runtime = ExecutionRuntime(
        transport=transport,  # type: ignore[arg-type]
        workspaces=workspaces,
        execution_lock=lock,  # type: ignore[arg-type]
        resolver=_resolver(lambda _pid: current_identity[0]),
        lock_timeout_seconds=1,
    )

    with pytest.raises(BridgeError) as caught:
        runtime.execute(session, _invocation("result = 1\n"))

    assert caught.value.code == "session_unreachable"
    assert transport.calls == 0
    assert lock.active is False
    assert list(workspaces.root.iterdir()) == []


def test_runtime_rejects_same_pid_new_incarnation_for_legacy_record(
    tmp_path: Path,
) -> None:
    legacy_record = SessionRecord(1, 49152, 1001, None)
    session = ResolvedSession(
        record=legacy_record,
        identity=ProcessIdentity(1001, "old-incarnation"),
        probe=_resolved_session().probe,
    )
    workspaces = TemporaryWorkspaceService(temp_root=tmp_path / "temp")
    lock = RecordingLock()

    class NoDispatch:
        calls = 0

        def execute_script(self, target, script_path):
            self.calls += 1
            raise AssertionError("replacement incarnation must not dispatch")

    transport = NoDispatch()
    runtime = ExecutionRuntime(
        transport=transport,  # type: ignore[arg-type]
        workspaces=workspaces,
        execution_lock=lock,  # type: ignore[arg-type]
        resolver=_resolver(lambda _pid: ProcessIdentity(1001, "new-incarnation")),
        lock_timeout_seconds=1,
    )

    with pytest.raises(BridgeError) as caught:
        runtime.execute(session, _invocation("result = 1\n"))

    assert caught.value.code == "session_unreachable"
    assert transport.calls == 0
    assert lock.active is False
    assert list(workspaces.root.iterdir()) == []


@pytest.mark.parametrize("change_at", ["history_prepare", "script_staging"])
def test_runtime_revalidates_after_history_preparation_and_script_staging(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change_at: str
) -> None:
    from houbridge.execution import runtime as runtime_module

    session = _resolved_session()
    current_identity = [session.identity]
    workspaces = TemporaryWorkspaceService(temp_root=tmp_path / "temp")
    lock = RecordingLock()
    staged = []

    class History:
        def prepare(self, invocation, original_session, workspace):
            if change_at == "history_prepare":
                current_identity[0] = ProcessIdentity(1001, "new-incarnation")
            return None

    original_stage = runtime_module.ExecutionScriptBuilder.stage

    def tracking_stage(builder, workspace, request_path):
        result = original_stage(builder, workspace, request_path)
        staged.append(result.script_path)
        if change_at == "script_staging":
            current_identity[0] = ProcessIdentity(1001, "new-incarnation")
        return result

    monkeypatch.setattr(runtime_module.ExecutionScriptBuilder, "stage", tracking_stage)

    class NoDispatch:
        calls = 0

        def execute_script(self, target, script_path):
            self.calls += 1
            raise AssertionError("changed Session must not dispatch")

    transport = NoDispatch()
    runtime = ExecutionRuntime(
        transport=transport,  # type: ignore[arg-type]
        workspaces=workspaces,
        execution_lock=lock,  # type: ignore[arg-type]
        resolver=_resolver(lambda _pid: current_identity[0]),
        lock_timeout_seconds=1,
        history=History(),  # type: ignore[arg-type]
    )

    with pytest.raises(BridgeError) as caught:
        runtime.execute(session, _invocation("result = 1\n"))

    assert caught.value.code == "session_unreachable"
    assert staged
    assert transport.calls == 0
    assert lock.active is False
    assert list(workspaces.root.iterdir()) == []


def test_transport_failure_propagates_and_workspace_is_removed(tmp_path: Path) -> None:
    workspaces = TemporaryWorkspaceService(temp_root=tmp_path)
    lock = RecordingLock()
    runtime = ExecutionRuntime(
        transport=FailingTransport(),  # type: ignore[arg-type]
        workspaces=workspaces,
        execution_lock=lock,  # type: ignore[arg-type]
        resolver=_resolver(),
        lock_timeout_seconds=1,
    )

    with pytest.raises(BridgeError) as caught:
        runtime.execute(_resolved_session(), _invocation("result = 1\n"))

    assert caught.value.code == "houdini_transport_failed"
    assert list(workspaces.root.iterdir()) == []


def test_history_enabled_timeout_after_terminal_status_preserves_python_outcome(
    tmp_path: Path,
) -> None:
    fake_hou_root = tmp_path / "fake"
    fake_hou_root.mkdir()
    (fake_hou_root / "hou.py").write_text("VALUE = 7\n", encoding="utf-8")
    workspaces = TemporaryWorkspaceService(temp_root=tmp_path / "temp")
    lock = RecordingLock()
    transport = TimeoutAfterScriptTransport(fake_hou_root, lock)

    class History:
        def __init__(self) -> None:
            self.finalize_calls = 0

        def prepare(self, invocation, session, workspace):
            runtime_script = workspace.path_for("history-runtime.py")
            runtime_script.write_text(
                "def prepare(_request_file):\n"
                "    return object()\n"
                "def finalize(_context):\n"
                "    return None\n",
                encoding="utf-8",
            )
            request_path = workspace.path_for("history-request.json")
            request_path.write_text("{}", encoding="utf-8")
            return type(
                "Preparation",
                (),
                {"runtime_script": runtime_script, "request_path": request_path},
            )()

        def finalize(self, preparation, invocation, session, outcome, workspace):
            self.finalize_calls += 1

    history = History()
    runtime = ExecutionRuntime(
        transport=transport,  # type: ignore[arg-type]
        workspaces=workspaces,
        execution_lock=lock,  # type: ignore[arg-type]
        resolver=_resolver(),
        lock_timeout_seconds=1,
        history=history,  # type: ignore[arg-type]
    )

    outcome = runtime.execute(
        _resolved_session(),
        _invocation("print('done')\nresult = {'value': hou.VALUE}\n"),
    )

    assert outcome.python_ok is True
    assert outcome.stdout == "done\n"
    assert outcome.result is not None
    assert outcome.result.inline_value() == {"value": 7}
    assert history.finalize_calls == 1
    assert list(workspaces.root.iterdir()) == []


def test_timeout_after_terminal_status_without_history_remains_transport_failure(
    tmp_path: Path,
) -> None:
    fake_hou_root = tmp_path / "fake-no-history"
    fake_hou_root.mkdir()
    (fake_hou_root / "hou.py").write_text("VALUE = 7\n", encoding="utf-8")
    workspaces = TemporaryWorkspaceService(temp_root=tmp_path / "temp-no-history")
    lock = RecordingLock()
    runtime = ExecutionRuntime(
        transport=TimeoutAfterScriptTransport(fake_hou_root, lock),  # type: ignore[arg-type]
        workspaces=workspaces,
        execution_lock=lock,  # type: ignore[arg-type]
        resolver=_resolver(),
        lock_timeout_seconds=1,
        history=None,
    )

    with pytest.raises(BridgeError) as caught:
        runtime.execute(_resolved_session(), _invocation("result = hou.VALUE\n"))

    assert caught.value.code == "hcommand_timeout"
    assert list(workspaces.root.iterdir()) == []


def test_runtime_rejects_nul_before_workspace_or_transport(tmp_path: Path) -> None:
    workspaces = TemporaryWorkspaceService(temp_root=tmp_path)
    lock = RecordingLock()
    runtime = ExecutionRuntime(
        transport=FailingTransport(),  # type: ignore[arg-type]
        workspaces=workspaces,
        execution_lock=lock,  # type: ignore[arg-type]
        resolver=_resolver(),
        lock_timeout_seconds=1,
    )

    with pytest.raises(BridgeError) as caught:
        runtime.execute(_resolved_session(), _invocation("pass\x00\n"))

    assert caught.value.code == "invalid_python_source"
    assert not workspaces.root.exists() or list(workspaces.root.iterdir()) == []
    assert lock.identities == []
