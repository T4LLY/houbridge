from __future__ import annotations

from houbridge.session.resolver import SessionResolver

from .models import ExecutionInvocation
from .presentation import ExecutionResultPresenter, SynchronousExecutionResult
from .runtime import ExecutionRuntime


class SynchronousExecutionService:
    """Resolve one registered session, execute once, and build its sync result."""

    def __init__(
        self,
        resolver: SessionResolver,
        runtime: ExecutionRuntime,
        presenter: ExecutionResultPresenter,
    ) -> None:
        self._resolver = resolver
        self._runtime = runtime
        self._presenter = presenter

    def execute(
        self,
        invocation: ExecutionInvocation,
        *,
        session: int | None = None,
    ) -> SynchronousExecutionResult:
        resolved = self._resolver.resolve(session)
        outcome = self._runtime.execute(resolved, invocation)
        return self._presenter.present(outcome)
