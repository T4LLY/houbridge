from __future__ import annotations

from houbridge.execution.models import ExecutionInvocation, ExecutionOutcome
from houbridge.execution.presentation import SynchronousExecutionResult
from houbridge.execution.service import SynchronousExecutionService
from houbridge.houdini.transport import HoudiniTarget
from houbridge.process_coordination import ProcessIdentity
from houbridge.session.probe import SessionProbeResult
from houbridge.session.registry import SessionRecord
from houbridge.session.resolver import ResolvedSession


def _resolved() -> ResolvedSession:
    record = SessionRecord(3, 49154, 1003, "start-3")
    return ResolvedSession(
        record=record,
        identity=ProcessIdentity(1003, "start-3"),
        probe=SessionProbeResult(
            pid=1003,
            version="22.0.1",
            license="Commercial",
            file=None,
            headless=False,
            open_ports=(49154,),
        ),
    )


def _invocation() -> ExecutionInvocation:
    return ExecutionInvocation(
        source="result = 7\n",
        source_path="tool.py",
        argv=("tool.py", "one"),
        purpose="build preview geometry",
        origin_cwd="/caller",
    )


class Resolver:
    def __init__(self, resolved: ResolvedSession) -> None:
        self.resolved = resolved
        self.selections: list[int | None] = []

    def resolve(self, session: int | None = None) -> ResolvedSession:
        self.selections.append(session)
        return self.resolved


class Runtime:
    def __init__(self, outcome: ExecutionOutcome) -> None:
        self.outcome = outcome
        self.calls: list[tuple[ResolvedSession, ExecutionInvocation]] = []

    def execute(
        self,
        session: ResolvedSession,
        invocation: ExecutionInvocation,
    ) -> ExecutionOutcome:
        self.calls.append((session, invocation))
        return self.outcome


class Presenter:
    def __init__(self, result: SynchronousExecutionResult) -> None:
        self.result = result
        self.outcomes: list[ExecutionOutcome] = []

    def present(self, outcome: ExecutionOutcome) -> SynchronousExecutionResult:
        self.outcomes.append(outcome)
        return self.result


def test_service_resolves_selected_session_then_executes_once_and_presents() -> None:
    resolved = _resolved()
    outcome = ExecutionOutcome(True, None, "done\n", "", None)
    public = SynchronousExecutionResult({"stdout": "done\n"}, 0)
    resolver = Resolver(resolved)
    runtime = Runtime(outcome)
    presenter = Presenter(public)
    service = SynchronousExecutionService(
        resolver,  # type: ignore[arg-type]
        runtime,  # type: ignore[arg-type]
        presenter,  # type: ignore[arg-type]
    )
    invocation = _invocation()

    result = service.execute(invocation, session=3)

    assert result is public
    assert resolver.selections == [3]
    assert runtime.calls == [(resolved, invocation)]
    assert presenter.outcomes == [outcome]
    assert resolved.target == HoudiniTarget("127.0.0.1", 49154)
