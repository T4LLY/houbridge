from __future__ import annotations

from typing import Protocol

from houbridge.session.resolver import ResolvedSession

from .models import ExecutionInvocation, ExecutionOutcome


class ExecutionHistoryBoundary(Protocol):
    """Service seam reserved for Action History integration in the History phase.

    Phase 14 intentionally supplies no implementation. The boundary keeps the
    Execution core independent from History repositories, schemas, snapshots,
    identities, recipes, and recovery state.
    """

    def prepare(
        self,
        invocation: ExecutionInvocation,
        session: ResolvedSession,
    ) -> object: ...

    def finalize(
        self,
        preparation: object,
        invocation: ExecutionInvocation,
        session: ResolvedSession,
        outcome: ExecutionOutcome,
    ) -> None: ...
