from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from houbridge.cli.common import emit_result
from houbridge.config import HARD_EMIT_LIMIT_BYTES, HARD_INLINE_TOKEN_LIMIT
from houbridge.errors import BridgeError
from houbridge.output.json import serialize_public_json
from houbridge.output.policy import OutputPolicy
from houbridge.output.tokens import FallbackTokenEstimator


class _RecordingStore:
    def __init__(self, alias: str = "output-policy-resource-000") -> None:
        self.alias = alias
        self.payloads: list[bytes] = []

    def put_bytes(self, payload: bytes):
        self.payloads.append(payload)
        return SimpleNamespace(semantic_alias=self.alias)


def _policy(
    *,
    inline_max_tokens: int,
    store: _RecordingStore | None = None,
) -> tuple[OutputPolicy, _RecordingStore]:
    active_store = store or _RecordingStore()
    return (
        OutputPolicy(
            inline_max_tokens=inline_max_tokens,
            token_estimator=FallbackTokenEstimator(),
            resource_store_factory=lambda: active_store,
        ),
        active_store,
    )


def test_from_config_reuses_output_estimator_for_resource_metadata(monkeypatch) -> None:
    captured: dict[str, object] = {}
    config = SimpleNamespace(output=SimpleNamespace(inline_max_tokens=256))
    store = _RecordingStore()

    def from_config(received_config, *, token_estimator):
        captured["config"] = received_config
        captured["estimator"] = token_estimator
        return store

    monkeypatch.setattr(
        "houbridge.output.policy.ResourceStore.from_config",
        from_config,
    )

    policy = OutputPolicy.from_config(config)  # type: ignore[arg-type]

    assert policy.resource_store_factory() is store
    assert captured["config"] is config
    assert captured["estimator"] is policy.token_estimator


def test_small_logical_result_remains_inline_without_opening_resource_store() -> None:
    opened = False

    def open_store():
        nonlocal opened
        opened = True
        return _RecordingStore()

    policy = OutputPolicy(
        inline_max_tokens=256,
        token_estimator=FallbackTokenEstimator(),
        resource_store_factory=open_store,
    )

    assert policy.render({"session": 1, "pid": 42}) == '{"session":1,"pid":42}'
    assert opened is False


def test_soft_threshold_resourceizes_the_complete_logical_result_once() -> None:
    policy, store = _policy(inline_max_tokens=1)
    logical = {"hits": [{"path": "/obj/geo1", "score": 1.0}]}

    rendered = policy.render(logical)

    assert rendered == '{"resource":"output-policy-resource-000"}'
    assert store.payloads == [serialize_public_json(logical).encode("utf-8")]


def test_bounded_resource_inspection_skips_recursive_resource_fallback() -> None:
    policy, store = _policy(inline_max_tokens=1)
    logical = {"result": "inspection body"}

    rendered = policy.render(logical, allow_resource_fallback=False)

    assert rendered == '{"result":"inspection body"}'
    assert store.payloads == []


def test_whole_result_fallback_keeps_very_large_logical_result_within_hard_limit() -> None:
    policy, store = _policy(inline_max_tokens=1)
    logical = {"result": "x" * (HARD_EMIT_LIMIT_BYTES * 2)}

    rendered = policy.render(logical)

    assert rendered == '{"resource":"output-policy-resource-000"}'
    assert store.payloads == [serialize_public_json(logical).encode("utf-8")]
    assert len(rendered.encode("utf-8")) < HARD_EMIT_LIMIT_BYTES


def test_final_hard_boundary_rejects_oversized_non_fallback_response() -> None:
    policy, _store = _policy(inline_max_tokens=HARD_INLINE_TOKEN_LIMIT)
    logical = {"result": "x" * HARD_EMIT_LIMIT_BYTES}

    with pytest.raises(BridgeError) as exc_info:
        policy.render(logical, allow_resource_fallback=False)

    error = exc_info.value
    assert error.code == "output_too_large"
    assert error.message == (
        "CLI output exceeds the hard limit and must be returned as a Resource."
    )
    assert "hard_limit_bytes=65536" in (error.detail or "")


def test_final_hard_boundary_runs_after_resource_fallback() -> None:
    store = _RecordingStore(alias="r" * HARD_EMIT_LIMIT_BYTES)
    policy, _store = _policy(inline_max_tokens=1, store=store)

    with pytest.raises(BridgeError) as exc_info:
        policy.render({"result": "large enough"})

    assert exc_info.value.code == "output_too_large"
    assert len(store.payloads) == 1


def test_policy_rejects_soft_threshold_above_fixed_token_ceiling() -> None:
    with pytest.raises(ValueError, match="4096"):
        OutputPolicy(
            inline_max_tokens=HARD_INLINE_TOKEN_LIMIT + 1,
            token_estimator=FallbackTokenEstimator(),
            resource_store_factory=_RecordingStore,
        )


def test_emit_result_converts_final_hard_failure_to_bounded_nonzero_json(monkeypatch, capsys) -> None:
    policy, _store = _policy(inline_max_tokens=HARD_INLINE_TOKEN_LIMIT)

    monkeypatch.setattr(
        "houbridge.cli.common.OutputPolicy.from_config",
        lambda _config: policy,
    )

    with pytest.raises(SystemExit) as exc_info:
        emit_result(
            {"result": "x" * HARD_EMIT_LIMIT_BYTES},
            allow_resource_fallback=False,
        )

    assert exc_info.value.code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["error"] is True
    assert payload["code"] == "output_too_large"
    assert "hard_limit_bytes=65536" in payload["detail"]


def test_oversized_error_detail_is_replaced_by_bounded_hard_limit_error(capsys) -> None:
    from houbridge.cli.common import terminate_with_bridge_error

    with pytest.raises(SystemExit) as exc_info:
        terminate_with_bridge_error(
            BridgeError("example_error", "failed", "x" * HARD_EMIT_LIMIT_BYTES)
        )

    assert exc_info.value.code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["error"] is True
    assert payload["code"] == "output_too_large"
    assert len(json.dumps(payload).encode("utf-8")) < HARD_EMIT_LIMIT_BYTES
