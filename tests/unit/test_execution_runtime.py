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
from houbridge.session.resolver import ResolvedSession
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


def test_transport_failure_propagates_and_workspace_is_removed(tmp_path: Path) -> None:
    workspaces = TemporaryWorkspaceService(temp_root=tmp_path)
    lock = RecordingLock()
    runtime = ExecutionRuntime(
        transport=FailingTransport(),  # type: ignore[arg-type]
        workspaces=workspaces,
        execution_lock=lock,  # type: ignore[arg-type]
        lock_timeout_seconds=1,
    )

    with pytest.raises(BridgeError) as caught:
        runtime.execute(_resolved_session(), _invocation("result = 1\n"))

    assert caught.value.code == "houdini_transport_failed"
    assert list(workspaces.root.iterdir()) == []


def test_runtime_rejects_nul_before_workspace_or_transport(tmp_path: Path) -> None:
    workspaces = TemporaryWorkspaceService(temp_root=tmp_path)
    lock = RecordingLock()
    runtime = ExecutionRuntime(
        transport=FailingTransport(),  # type: ignore[arg-type]
        workspaces=workspaces,
        execution_lock=lock,  # type: ignore[arg-type]
        lock_timeout_seconds=1,
    )

    with pytest.raises(BridgeError) as caught:
        runtime.execute(_resolved_session(), _invocation("pass\x00\n"))

    assert caught.value.code == "invalid_python_source"
    assert not workspaces.root.exists() or list(workspaces.root.iterdir()) == []
    assert lock.identities == []
