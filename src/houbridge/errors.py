from __future__ import annotations


class BridgeError(RuntimeError):
    """Handled Houbridge failure exposed through the public CLI envelope."""

    def __init__(self, code: str, message: str, detail: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail if detail else None
