from __future__ import annotations

from pathlib import Path
from typing import Protocol

from houbridge.session.resolver import ResolvedSession
from houbridge.temporary_workspace import TemporaryWorkspace

from .models import ExecutionInvocation, ExecutionOutcome


class ExecutionHistoryPreparation(Protocol):
    """Opaque History state prepared before caller Python is allowed to start."""

    @property
    def runtime_script(self) -> Path: ...

    @property
    def request_path(self) -> Path: ...


class ExecutionHistoryBoundary(Protocol):
    """Execution-owned seam for optional Action History integration.

    Execution controls ordering. History owns its store, source embedding, Houdini
    instrumentation, Action Change materialization, and final persistence.
    """

    def prepare(
        self,
        invocation: ExecutionInvocation,
        session: ResolvedSession,
        workspace: TemporaryWorkspace,
    ) -> ExecutionHistoryPreparation: ...

    def finalize(
        self,
        preparation: ExecutionHistoryPreparation,
        invocation: ExecutionInvocation,
        session: ResolvedSession,
        outcome: ExecutionOutcome,
        workspace: TemporaryWorkspace,
    ) -> None: ...
