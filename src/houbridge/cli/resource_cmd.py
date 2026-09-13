from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

import typer

from houbridge.cli.common import (
    create_cli_app,
    emit_result,
    terminate_with_bridge_error,
)
from houbridge.config import load_config
from houbridge.errors import BridgeError
from houbridge.resource.dump import ResourceDumper
from houbridge.resource.reader import ResourceReader
from houbridge.resource.store import ResourceStore
from houbridge.temporary_artifact import TemporaryArtifactService


resource_app = create_cli_app(no_args_is_help=True)


def _reader() -> ResourceReader:
    settings = load_config()
    return ResourceReader(
        ResourceStore.from_config(settings),
        inline_limit_bytes=settings.resource.inline_limit_bytes,
        search_limit=settings.resource.search_limit,
    )


def _dumper() -> ResourceDumper:
    settings = load_config()
    try:
        artifacts = TemporaryArtifactService()
    except OSError as exc:
        raise BridgeError(
            "resource_dump_failed",
            "Unable to initialize Resource dump storage.",
            f"{type(exc).__name__}: {exc}",
        ) from exc
    return ResourceDumper(
        ResourceStore.from_config(settings),
        artifacts,
        ttl_hours=settings.resource.ttl_hours,
    )


def _emit_resource(operation: Callable[[], Mapping[str, Any]]) -> None:
    try:
        emit_result(operation(), allow_resource_fallback=False)
    except BridgeError as exc:
        terminate_with_bridge_error(exc)


@resource_app.command("info", help="Show resource metadata.")
def info_command(resource_id: str) -> None:
    _emit_resource(lambda: _reader().info(resource_id))


@resource_app.command("get", help="Retrieve a resource.")
def get_command(
    resource_id: str,
    full: bool = typer.Option(False, "--full"),
) -> None:
    _emit_resource(lambda: _reader().get(resource_id, full=full))


@resource_app.command("slice", help="Retrieve a byte or text range from a resource.")
def slice_command(
    resource_id: str,
    offset: int = typer.Option(..., "--offset"),
    limit: int = typer.Option(..., "--limit"),
) -> None:
    _emit_resource(lambda: _reader().slice(resource_id, offset=offset, limit=limit))


@resource_app.command("search", help="Search within a resource.")
def search_command(
    resource_id: str,
    query: str,
    offset: int = typer.Option(0, "--offset"),
) -> None:
    _emit_resource(lambda: _reader().search(resource_id, query, offset=offset))


@resource_app.command("dump", help="Write a resource to a temporary file.")
def dump_command(resource_id: str) -> None:
    _emit_resource(lambda: _dumper().dump(resource_id))
