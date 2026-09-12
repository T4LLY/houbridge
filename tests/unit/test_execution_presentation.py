from __future__ import annotations

from houbridge.execution.models import DeclaredResult, ExecutionOutcome
from houbridge.execution.presentation import ExecutionResultPresenter
from houbridge.output.policy import OutputPolicy
from houbridge.resource.models import Resource


class ByteCountEstimator:
    def count(self, text: str) -> int:
        return len(text.encode("utf-8"))


class RecordingResourceStore:
    def __init__(self) -> None:
        self.payloads: list[bytes] = []

    def put_bytes(self, payload: bytes) -> Resource:
        self.payloads.append(payload)
        index = len(self.payloads)
        is_json = payload.startswith((b"{", b"["))
        return Resource(
            canonical_id=f"canonical-{index}",
            semantic_alias=f"execution-artifact-{index:03d}",
            content_class="json" if is_json else "text",
            mime="application/json" if is_json else "text/plain",
            byte_size=len(payload),
            token_count=len(payload),
            created_at="2026-09-11T00:00:00+00:00",
            expires_at="2026-09-14T00:00:00+00:00",
        )

    def put_text(self, text: str) -> Resource:
        return self.put_bytes(text.encode("utf-8"))


def _presenter(limit: int) -> tuple[ExecutionResultPresenter, RecordingResourceStore]:
    store = RecordingResourceStore()
    policy = OutputPolicy(
        inline_max_tokens=limit,
        token_estimator=ByteCountEstimator(),
        resource_store_factory=lambda: store,  # type: ignore[arg-type]
    )
    return ExecutionResultPresenter(policy), store


def test_success_keeps_small_bodies_inline_without_per_artifact_resources() -> None:
    presenter, store = _presenter(64)
    outcome = ExecutionOutcome(
        python_ok=True,
        result=DeclaredResult("json", b'{"value":7}'),
        stdout="hello\n",
        stderr="warning\n",
        traceback=None,
    )

    result = presenter.present(outcome)

    assert result.exit_code == 0
    assert result.payload == {
        "result": {"value": 7},
        "stdout": "hello\n",
        "stderr": "warning\n",
    }
    assert store.payloads == []


def test_success_resourceizes_each_large_body_independently() -> None:
    presenter, store = _presenter(5)
    outcome = ExecutionOutcome(
        python_ok=True,
        result=DeclaredResult("json", b'{"value":7}'),
        stdout="ok",
        stderr="abcdef",
        traceback=None,
    )

    result = presenter.present(outcome)

    assert result.exit_code == 0
    assert result.payload == {
        "resource": "execution-artifact-001",
        "mime": "application/json",
        "tokens": 11,
        "stdout": "ok",
        "stderr_resource": "execution-artifact-002",
    }
    assert store.payloads == [b'{"value":7}', b"abcdef"]


def test_python_failure_uses_fixed_envelope_and_traceback_resource() -> None:
    presenter, store = _presenter(64)
    outcome = ExecutionOutcome(
        python_ok=False,
        result=None,
        stdout="before failure\n",
        stderr="",
        traceback="Traceback (most recent call last):\nRuntimeError: boom\n",
    )

    result = presenter.present(outcome)

    assert result.exit_code == 1
    assert result.payload == {
        "error": True,
        "code": "execution_failed",
        "message": "Python execution failed inside Houdini.",
        "resource": "execution-artifact-001",
        "stdout": "before failure\n",
    }
    assert store.payloads == [outcome.traceback.encode("utf-8")]


def test_no_public_execution_output_can_be_empty_object() -> None:
    presenter, store = _presenter(64)
    outcome = ExecutionOutcome(
        python_ok=True,
        result=None,
        stdout="",
        stderr="",
        traceback=None,
    )

    result = presenter.present(outcome)

    assert result.payload == {}
    assert result.exit_code == 0
    assert store.payloads == []


def test_empty_plain_text_declared_result_adds_no_public_body() -> None:
    presenter, store = _presenter(64)
    outcome = ExecutionOutcome(
        python_ok=True,
        result=DeclaredResult("text", b""),
        stdout="",
        stderr="",
        traceback=None,
    )

    result = presenter.present(outcome)

    assert result.payload == {}
    assert store.payloads == []
