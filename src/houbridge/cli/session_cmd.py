from __future__ import annotations

from pathlib import Path

import typer

from houbridge.cli.common import create_cli_app, emit_result
from houbridge.config import load_config
from houbridge.houdini.installations import resolve_transport_hcommand_for_launch
from houbridge.houdini.transport import HoudiniTransport
from houbridge.paths import GlobalDataPaths
from houbridge.session.info import SessionInfoService
from houbridge.session.launcher import HoudiniSessionLauncher
from houbridge.session.new import SessionNewService
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


@session_app.command("new")
def new_command(
    hip_file: Path | None = typer.Option(None, "--file"),
    headless: bool = typer.Option(False, "--headless"),
    hcommand: Path | None = typer.Option(None, "--hcommand"),
) -> None:
    settings = load_config()
    paths = GlobalDataPaths.from_data_dir(settings.storage.data_dir)
    registry = SessionRegistry(paths.sessions_registry)
    def probe_for_launch(executable: Path) -> SessionProbe:
        transport_executable = resolve_transport_hcommand_for_launch(executable)
        return SessionProbe(
            lambda: HoudiniTransport(
                transport_executable,
                timeout_seconds=settings.houdini.transport_timeout_seconds,
            )
        )

    launcher = HoudiniSessionLauncher(settings.houdini, probe_for_launch)
    payload = SessionNewService(registry, launcher).create(
        hip_file=hip_file,
        headless=headless,
        hcommand=hcommand,
    )
    emit_result(payload)
