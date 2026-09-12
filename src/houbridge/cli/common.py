from __future__ import annotations

from collections.abc import Mapping
from typing import Any, NoReturn

import typer

from houbridge.config import load_config
from houbridge.errors import BridgeError
from houbridge.output.json import serialize_public_json
from houbridge.output.policy import OutputPolicy, enforce_final_json_boundary


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


def serialize_result(payload: Mapping[str, Any]) -> str:
    """Serialize one public machine result as compact UTF-8-safe JSON text."""

    return serialize_public_json(payload)


def emit_result(
    payload: Mapping[str, Any],
    *,
    allow_resource_fallback: bool = True,
    policy: OutputPolicy | None = None,
) -> None:
    """Apply the common Output Policy and emit exactly one public JSON result."""

    try:
        active_policy = policy or OutputPolicy.from_config(load_config())
        serialized = active_policy.render(
            payload,
            allow_resource_fallback=allow_resource_fallback,
        )
    except BridgeError as exc:
        terminate_with_bridge_error(exc)
    typer.echo(serialized)


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


def _emit_bounded_error(payload: Mapping[str, Any]) -> None:
    try:
        serialized = enforce_final_json_boundary(payload)
    except BridgeError as exc:
        serialized = enforce_final_json_boundary(bridge_error_payload(exc))
    typer.echo(serialized)


def terminate_with_bridge_error(error: BridgeError) -> NoReturn:
    _emit_bounded_error(bridge_error_payload(error))
    raise SystemExit(1)


def terminate_with_internal_error(error: Exception) -> NoReturn:
    _emit_bounded_error(internal_error_payload(error))
    raise SystemExit(1)
