from __future__ import annotations

from collections.abc import Mapping


class BridgeError(RuntimeError):
    """Handled Houbridge failure exposed through the public CLI envelope."""

    def __init__(
        self,
        code: str,
        message: str,
        detail: str | None = None,
        *,
        context: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail if detail else None
        self.context = dict(context) if context else None
