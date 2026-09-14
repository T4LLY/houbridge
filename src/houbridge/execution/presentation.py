from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from houbridge.output.policy import OutputPolicy
from houbridge.resource.store import ResourceStore

from .models import DeclaredResult, ExecutionOutcome


_EXECUTION_FAILURE_MESSAGE = "Python execution failed inside Houdini."


class ExecutionPresentationMode(str, Enum):
    """Select only how synchronous execution artifacts cross the CLI boundary."""

    NORMAL = "normal"
    FULL = "full"


@dataclass(frozen=True, slots=True)
class SynchronousExecutionResult:
    """Logical public result plus the process exit code for one sync execution."""

    payload: dict[str, Any]
    exit_code: int


class ExecutionResultPresenter:
    """Build the command-specific sync envelope using Resource/Output boundaries."""

    def __init__(
        self,
        output_policy: OutputPolicy,
        *,
        mode: ExecutionPresentationMode = ExecutionPresentationMode.NORMAL,
    ) -> None:
        self._output_policy = output_policy
        self._mode = mode
        self._resource_store: ResourceStore | None = None

    def present(self, outcome: ExecutionOutcome) -> SynchronousExecutionResult:
        if outcome.python_ok:
            payload: dict[str, Any] = {}
            if outcome.result is not None and outcome.result.payload:
                self._add_declared_result(payload, outcome.result)
            exit_code = 0
        else:
            payload = {
                "error": True,
                "code": "execution_failed",
                "message": _EXECUTION_FAILURE_MESSAGE,
            }
            if outcome.traceback:
                payload["resource"] = self._store().put_text(outcome.traceback).semantic_alias
            exit_code = 1

        self._add_text_body(payload, "stdout", outcome.stdout)
        self._add_text_body(payload, "stderr", outcome.stderr)
        return SynchronousExecutionResult(payload=payload, exit_code=exit_code)

    def _add_declared_result(
        self,
        payload: dict[str, Any],
        result: DeclaredResult,
    ) -> None:
        serialized_body = result.payload.decode("utf-8", errors="strict")
        if self._keeps_artifact_inline(serialized_body):
            payload["result"] = result.inline_value()
            return

        resource = self._store().put_bytes(result.payload)
        payload["resource"] = resource.semantic_alias
        payload["mime"] = resource.mime
        if resource.token_count is not None:
            payload["tokens"] = resource.token_count

    def _add_text_body(
        self,
        payload: dict[str, Any],
        field: str,
        body: str,
    ) -> None:
        if not body:
            return
        if self._keeps_artifact_inline(body):
            payload[field] = body
            return

        resource = self._store().put_text(body)
        payload[f"{field}_resource"] = resource.semantic_alias

    def _keeps_artifact_inline(self, serialized_body: str) -> bool:
        return (
            self._mode is ExecutionPresentationMode.FULL
            or self._output_policy.permits_inline_text(serialized_body)
        )

    def _store(self) -> ResourceStore:
        if self._resource_store is None:
            self._resource_store = self._output_policy.resource_store_factory()
        return self._resource_store
