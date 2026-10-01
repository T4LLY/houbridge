from __future__ import annotations

import typer

from houbridge.cli.common import create_cli_app, emit_result, terminate_with_bridge_error
from houbridge.config import HoubridgeConfig, load_config
from houbridge.errors import BridgeError
from houbridge.hip import HipFileService
from houbridge.houdini.transport import HoudiniTransport
from houbridge.output.policy import OutputPolicy
from houbridge.paths import GlobalDataPaths
from houbridge.session.probe import SessionProbe
from houbridge.session.registry import SessionRegistry
from houbridge.session.resolver import SessionResolver


hip_app = create_cli_app(
    no_args_is_help=True,
    help="Inspect and save the current HIP file.",
)


def _service_and_resolver(settings: HoubridgeConfig) -> tuple[HipFileService, SessionResolver]:
    paths = GlobalDataPaths.from_data_dir(settings.storage.data_dir)
    registry = SessionRegistry(
        paths.sessions_registry,
        lock_timeout_seconds=settings.houdini.lock_timeout_seconds,
    )
    transport = HoudiniTransport.from_config(settings.houdini)
    probe = SessionProbe(lambda: transport)
    return HipFileService(transport), SessionResolver(registry, probe)


def _run(mode: str, session: int | None) -> None:
    try:
        settings = load_config()
        service, resolver = _service_and_resolver(settings)
        resolved = resolver.resolve(session)
        payload = service.save(resolved) if mode == "save" else service.info(resolved)
        emit_result(payload, policy=OutputPolicy.from_config(settings))
    except BridgeError as exc:
        terminate_with_bridge_error(exc)


@hip_app.command("info", help="Show the current HIP file state.")
def info_command(
    session: int | None = typer.Option(
        None,
        "--session",
        min=1,
        help="Target this registered session instead of the primary session.",
    ),
) -> None:
    _run("info", session)


@hip_app.command("save", help="Save the current HIP file to its existing path.")
def save_command(
    session: int | None = typer.Option(
        None,
        "--session",
        min=1,
        help="Target this registered session instead of the primary session.",
    ),
) -> None:
    _run("save", session)
