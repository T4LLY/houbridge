from __future__ import annotations

from pathlib import Path

from houbridge.errors import BridgeError


def append_diagnostic_path(
    detail: str | None,
    directory: Path,
    *,
    label: str,
) -> str:
    marker = f"{label}={directory}"
    return f"{detail}; {marker}" if detail else marker


def write_failure(directory: Path, name: str, error: BaseException) -> None:
    try:
        if isinstance(error, BridgeError):
            detail = f"\ndetail: {error.detail}" if error.detail else ""
            text = f"code: {error.code}\nmessage: {error.message}{detail}\n"
        else:
            text = f"type: {type(error).__name__}\nmessage: {error}\n"
        (directory / name).write_text(text, encoding="utf-8")
    except OSError:
        pass


def write_text(directory: Path, name: str, value: str) -> None:
    try:
        (directory / name).write_text(value, encoding="utf-8")
    except OSError:
        pass
