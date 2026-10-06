from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from houbridge.execution.models import ExecutionInvocation
from houbridge.houdini.transport import HoudiniTransport
from houbridge.session.resolver import ResolvedSession

from .models import FrozenDispatchContext, TaskSubmission


def freeze_task_submission(
    invocation: "ExecutionInvocation",
    *,
    session: ResolvedSession,
    transport: HoudiniTransport,
    lock_timeout_seconds: float,
    history_enabled: bool,
    history_code_profile: str,
) -> TaskSubmission:
    """Freeze all mutable dispatch inputs needed after the submitting CLI exits."""

    origin_cwd = Path(invocation.origin_cwd).resolve()
    assert invocation.source_path is not None
    source_path = Path(invocation.source_path).expanduser()
    if not source_path.is_absolute():
        source_path = origin_cwd / source_path
    file_path = str(source_path.resolve())

    return TaskSubmission(
        source=invocation.source,
        file_path=file_path,
        argv=tuple(invocation.argv),
        purpose=invocation.purpose,
        origin_cwd=str(origin_cwd),
        dispatch=FrozenDispatchContext(
            session=session.record.session,
            port=session.record.port,
            pid=session.identity.pid,
            process_start_identity=session.identity.process_start_identity,
            transport_executable=str(transport.executable),
            transport_timeout_seconds=transport.timeout_seconds,
            transport_environment=transport.subprocess_environment(),
            lock_timeout_seconds=lock_timeout_seconds,
        ),
        history_enabled=bool(history_enabled),
        history_code_profile=history_code_profile,
    )
