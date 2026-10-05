from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import typer

from houbridge.cli.common import create_cli_app, emit_result
from houbridge.config import load_config
from houbridge.houdini.installations import resolve_transport_hcommand_for_launch
from houbridge.houdini.transport import HoudiniTransport
from houbridge.history.retirement import HistoryRetirementService
from houbridge.paths import GlobalDataPaths
from houbridge.process_coordination import ProcessIdentity
from houbridge.session.attach import SessionAttachService
from houbridge.session.detach import SessionDetachService
from houbridge.session.info import SessionInfoService
from houbridge.session.launcher import HoudiniSessionLauncher
from houbridge.session.new import SessionNewService
from houbridge.session.probe import SessionProbe
from houbridge.session.promote import SessionPromoteService
from houbridge.session.registry import SessionRecord, SessionRegistry
from houbridge.session.resolver import SessionResolver
from houbridge.session.stale import SessionStaleCleanupService


session_app = create_cli_app(no_args_is_help=True)


@session_app.command("info", help="Show active Houdini sessions.")
def info_command(
    session_number: int | None = typer.Option(
        None,
        "--session",
        help="Show only this registered session.",
    ),
) -> None:
    settings = load_config()
    paths = GlobalDataPaths.from_data_dir(settings.storage.data_dir)
    registry = SessionRegistry(
        paths.sessions_registry,
        lock_timeout_seconds=settings.houdini.lock_timeout_seconds,
    )
    probe = SessionProbe(lambda: HoudiniTransport.from_config(settings.houdini))
    resolver = SessionResolver(registry, probe)
    stale_cleanup = SessionStaleCleanupService(
        registry,
        on_stale=_history_retirement_callback(
            paths,
            lock_timeout_seconds=settings.houdini.lock_timeout_seconds,
        ),
    )
    payload = SessionInfoService(
        registry,
        resolver,
        stale_cleanup=stale_cleanup,
    ).inspect(session_number)
    emit_result(payload)


@session_app.command("new", help="Start a new Houdini session.")
def new_command(
    hip_file: Path | None = typer.Option(
        None,
        "--file",
        help="Open this HIP file in the new session.",
    ),
    headless: bool = typer.Option(
        False,
        "--headless",
        help="Launch the corresponding headless Houdini runtime.",
    ),
    hcommand: Path | None = typer.Option(
        None,
        "--hcommand",
        help="Override the configured Houdini launch executable.",
    ),
) -> None:
    settings = load_config()
    paths = GlobalDataPaths.from_data_dir(settings.storage.data_dir)
    registry = SessionRegistry(
        paths.sessions_registry,
        lock_timeout_seconds=settings.houdini.lock_timeout_seconds,
    )

    def probe_for_launch(executable: Path) -> SessionProbe:
        transport_executable = resolve_transport_hcommand_for_launch(executable)
        return SessionProbe(
            lambda: HoudiniTransport(
                transport_executable,
                timeout_seconds=settings.houdini.transport_timeout_seconds,
            )
        )

    launcher = HoudiniSessionLauncher(settings.houdini, probe_for_launch)
    retire_stale_history = _history_retirement_callback(
        paths,
        lock_timeout_seconds=settings.houdini.lock_timeout_seconds,
    )

    payload = SessionNewService(
        registry,
        launcher,
        on_stale=retire_stale_history,
    ).create(
        hip_file=hip_file,
        headless=headless,
        hcommand=hcommand,
    )
    emit_result(payload)


@session_app.command(
    "attach",
    help="Register an existing Houdini session that already has an openport.",
)
def attach_command(
    port: int = typer.Argument(
        ...,
        metavar="PORT",
        min=1,
        max=65535,
        help="Port printed by `openport -a -q` in the target Houdini Textport.",
    ),
) -> None:
    settings = load_config()
    paths = GlobalDataPaths.from_data_dir(settings.storage.data_dir)
    registry = SessionRegistry(
        paths.sessions_registry,
        lock_timeout_seconds=settings.houdini.lock_timeout_seconds,
    )
    probe = SessionProbe(lambda: HoudiniTransport.from_config(settings.houdini))
    payload = SessionAttachService(
        registry,
        probe,
        on_stale=_history_retirement_callback(
            paths,
            lock_timeout_seconds=settings.houdini.lock_timeout_seconds,
        ),
    ).attach(port)
    emit_result(payload)


@session_app.command(
    "detach",
    help="Unregister a session without stopping Houdini.",
)
def detach_command(
    session_number: int = typer.Argument(
        ...,
        metavar="SESSION",
        help="Registered session number to unregister.",
    ),
) -> None:
    settings = load_config()
    paths = GlobalDataPaths.from_data_dir(settings.storage.data_dir)
    registry = SessionRegistry(
        paths.sessions_registry,
        lock_timeout_seconds=settings.houdini.lock_timeout_seconds,
    )
    payload = SessionDetachService(registry).detach(session_number)
    emit_result(payload)


@session_app.command("promote", help="Set a session as the primary session.")
def promote_command(
    session_number: int = typer.Argument(
        ...,
        metavar="SESSION",
        help="Registered session number to make primary.",
    ),
) -> None:
    settings = load_config()
    paths = GlobalDataPaths.from_data_dir(settings.storage.data_dir)
    registry = SessionRegistry(
        paths.sessions_registry,
        lock_timeout_seconds=settings.houdini.lock_timeout_seconds,
    )
    probe = SessionProbe(lambda: HoudiniTransport.from_config(settings.houdini))
    resolver = SessionResolver(registry, probe)
    stale_cleanup = SessionStaleCleanupService(
        registry,
        on_stale=_history_retirement_callback(
            paths,
            lock_timeout_seconds=settings.houdini.lock_timeout_seconds,
        ),
    )
    payload = SessionPromoteService(
        registry,
        resolver,
        stale_cleanup=stale_cleanup,
    ).promote(session_number)
    emit_result(payload)


def _history_retirement_callback(
    paths: GlobalDataPaths,
    *,
    lock_timeout_seconds: float,
) -> Callable[[SessionRecord], None]:
    retirement = HistoryRetirementService(
        paths,
        lock_timeout_seconds=lock_timeout_seconds,
    )

    def retire(record: SessionRecord) -> None:
        if record.process_start_identity is None:
            return
        retirement.retire(ProcessIdentity(record.pid, record.process_start_identity))

    return retire
