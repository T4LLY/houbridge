from __future__ import annotations

import typer

from houbridge.cli.common import create_cli_app, emit_result
from houbridge.config import load_config
from houbridge.houdini.transport import HoudiniTransport
from houbridge.paths import GlobalDataPaths
from houbridge.session.info import SessionInfoService
from houbridge.session.probe import SessionProbe
from houbridge.session.registry import SessionRegistry
from houbridge.session.resolver import SessionResolver


session_app = create_cli_app(no_args_is_help=True)


@session_app.command("info")
def info_command(
    session_number: int | None = typer.Option(None, "--session"),
) -> None:
    settings = load_config()
    paths = GlobalDataPaths.from_data_dir(settings.storage.data_dir)
    registry = SessionRegistry(paths.sessions_registry)
    probe = SessionProbe(lambda: HoudiniTransport.from_config(settings.houdini))
    resolver = SessionResolver(registry, probe)
    payload = SessionInfoService(registry, resolver).inspect(session_number)
    emit_result(payload)
