from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from houbridge.config import (
    HARD_EMIT_LIMIT_BYTES,
    HARD_INLINE_TOKEN_LIMIT,
    HoubridgeConfig,
)
from houbridge.errors import BridgeError
from houbridge.output.json import serialize_public_json
from houbridge.output.tokens import FallbackTokenEstimator, TokenEstimator
from houbridge.resource.store import ResourceStore


ResourceStoreFactory = Callable[[], ResourceStore]


@dataclass(frozen=True, slots=True)
class OutputPolicy:
    """Single owner of soft inline decisions and final CLI output bounds."""

    inline_max_tokens: int
    token_estimator: TokenEstimator
    resource_store_factory: ResourceStoreFactory

    def __post_init__(self) -> None:
        if self.inline_max_tokens < 0:
            raise ValueError("inline_max_tokens must be >= 0")
        if self.inline_max_tokens > HARD_INLINE_TOKEN_LIMIT:
            raise ValueError(
                "inline_max_tokens must not exceed the fixed hard token limit "
                f"of {HARD_INLINE_TOKEN_LIMIT}"
            )

    @classmethod
    def from_config(cls, config: HoubridgeConfig) -> "OutputPolicy":
        estimator = FallbackTokenEstimator()
        return cls(
            inline_max_tokens=config.output.inline_max_tokens,
            token_estimator=estimator,
            resource_store_factory=lambda: ResourceStore.from_config(
                config,
                token_estimator=estimator,
            ),
        )

    def permits_inline_text(self, serialized_text: str) -> bool:
        """Return whether one serialized text/JSON body fits the shared soft budget."""

        return self.token_estimator.count(serialized_text) <= self.inline_max_tokens

    def present(
        self,
        payload: Mapping[str, Any],
        *,
        allow_resource_fallback: bool = True,
    ) -> Mapping[str, Any]:
        """Apply whole-result soft fallback without command-specific policy."""

        if not allow_resource_fallback:
            return payload

        serialized = serialize_public_json(payload)
        if self.permits_inline_text(serialized):
            return payload

        resource = self.resource_store_factory().put_bytes(serialized.encode("utf-8"))
        return {"resource": resource.semantic_alias}

    def render(
        self,
        payload: Mapping[str, Any],
        *,
        allow_resource_fallback: bool = True,
    ) -> str:
        """Apply soft fallback once, then enforce the fixed final JSON boundary."""

        presented = self.present(
            payload,
            allow_resource_fallback=allow_resource_fallback,
        )
        return enforce_final_json_boundary(presented)


def enforce_final_json_boundary(payload: Mapping[str, Any]) -> str:
    """Serialize and enforce the one fixed final CLI JSON byte boundary."""

    serialized = serialize_public_json(payload)
    size = len(serialized.encode("utf-8"))
    if size > HARD_EMIT_LIMIT_BYTES:
        raise output_too_large_error(size)
    return serialized


def output_too_large_error(serialized_bytes: int) -> BridgeError:
    return BridgeError(
        "output_too_large",
        "CLI output exceeds the hard limit and must be returned as a Resource.",
        f"bytes={serialized_bytes}; hard_limit_bytes={HARD_EMIT_LIMIT_BYTES}",
    )
