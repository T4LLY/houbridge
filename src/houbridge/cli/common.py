from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from typing import Any, NoReturn

import typer

from houbridge.errors import BridgeError
from houbridge.formatting import CanonicalJsonNumber


_INTERNAL_ERROR_MESSAGE = "Houbridge encountered an unexpected internal error."


def create_cli_app(**kwargs: Any) -> typer.Typer:
    """Create a root/subcommand Typer app without Rich/ANSI CLI decoration."""

    kwargs.setdefault("add_completion", False)
    return typer.Typer(
        rich_markup_mode=None,
        pretty_exceptions_enable=False,
        context_settings={"color": False},
        **kwargs,
    )


def _serialize_json(value: Any) -> str:
    if isinstance(value, CanonicalJsonNumber):
        return value.token
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("Public JSON does not support non-finite numbers.")
        return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    if isinstance(value, Mapping):
        parts: list[str] = []
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("Public JSON object keys must be strings.")
            parts.append(f"{json.dumps(key, ensure_ascii=False)}:{_serialize_json(item)}")
        return "{" + ",".join(parts) + "}"
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return "[" + ",".join(_serialize_json(item) for item in value) + "]"
    raise TypeError(f"Unsupported public JSON value: {type(value).__name__}")


def serialize_result(payload: Mapping[str, Any]) -> str:
    """Serialize one public machine result as compact UTF-8-safe JSON text."""

    return _serialize_json(payload)


def emit_result(payload: Mapping[str, Any]) -> None:
    typer.echo(serialize_result(payload))


def bridge_error_payload(error: BridgeError) -> dict[str, object]:
    payload: dict[str, object] = {
        "error": True,
        "code": error.code,
        "message": error.message,
    }
    if error.detail:
        payload["detail"] = error.detail
    return payload


def internal_error_payload(error: Exception) -> dict[str, object]:
    return {
        "error": True,
        "code": "internal_error",
        "message": _INTERNAL_ERROR_MESSAGE,
        "detail": f"{type(error).__name__}: {error}",
    }


def terminate_with_bridge_error(error: BridgeError) -> NoReturn:
    emit_result(bridge_error_payload(error))
    raise SystemExit(1)


def terminate_with_internal_error(error: Exception) -> NoReturn:
    emit_result(internal_error_payload(error))
    raise SystemExit(1)
