from __future__ import annotations

from pathlib import Path

import typer

from houbridge.capture import (
    CaptureArtifactPublisher,
    ScreenshotOCRService,
    ScreenshotService,
    TurntableService,
    ViewportInfoService,
    parse_turntable_pivot,
)
from houbridge.cli.common import create_cli_app, emit_result, terminate_with_bridge_error
from houbridge.config import HoubridgeConfig, load_config
from houbridge.errors import BridgeError
from houbridge.houdini.transport import HoudiniTransport
from houbridge.output.policy import OutputPolicy
from houbridge.paths import GlobalDataPaths
from houbridge.session.probe import SessionProbe
from houbridge.session.registry import SessionRegistry
from houbridge.session.resolver import SessionResolver
from houbridge.temporary_artifact import TemporaryArtifactService


capture_app = create_cli_app(
    no_args_is_help=True,
    help="Capture Houdini viewports, windows, and turntables.",
)


def _resolver_and_transport(settings: HoubridgeConfig) -> tuple[SessionResolver, HoudiniTransport]:
    paths = GlobalDataPaths.from_data_dir(settings.storage.data_dir)
    registry = SessionRegistry(paths.sessions_registry)
    transport = HoudiniTransport.from_config(settings.houdini)
    probe = SessionProbe(lambda: transport)
    return SessionResolver(registry, probe), transport


def _screenshot_service(
    settings: HoubridgeConfig,
    transport: HoudiniTransport,
) -> ScreenshotService:
    publisher = CaptureArtifactPublisher(
        TemporaryArtifactService(),
        settings.screenshot.retention_hours,
    )
    return ScreenshotService(
        transport,
        settings.screenshot,
        publisher,
    )


def _turntable_service(
    settings: HoubridgeConfig,
    transport: HoudiniTransport,
) -> TurntableService:
    publisher = CaptureArtifactPublisher(
        TemporaryArtifactService(),
        settings.screenshot.retention_hours,
    )
    return TurntableService(
        transport,
        settings.screenshot,
        publisher,
    )


@capture_app.command("viewport")
def viewport_command(
    info: bool = typer.Option(False, "--info"),
    top: bool = typer.Option(False, "--top"),
    bottom: bool = typer.Option(False, "--bottom"),
    front: bool = typer.Option(False, "--front"),
    back: bool = typer.Option(False, "--back"),
    left: bool = typer.Option(False, "--left"),
    right: bool = typer.Option(False, "--right"),
    persp: bool = typer.Option(False, "--persp"),
    uv: bool = typer.Option(False, "--uv"),
    quad: bool = typer.Option(False, "--quad"),
    scale: float = typer.Option(1.0, "--scale"),
    preset: Path | None = typer.Option(
        None,
        "--preset",
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
    ),
    session: int | None = typer.Option(None, "--session", min=1),
) -> None:
    selected = tuple(
        name
        for name, enabled in (
            ("top", top),
            ("bottom", bottom),
            ("front", front),
            ("back", back),
            ("left", left),
            ("right", right),
            ("persp", persp),
            ("uv", uv),
        )
        if enabled
    )
    if info and (selected or quad or scale != 1.0 or preset is not None):
        terminate_with_bridge_error(
            BridgeError(
                "capture_info_conflict",
                "--info cannot be combined with viewport capture options.",
            )
        )
    if quad and selected:
        terminate_with_bridge_error(
            BridgeError(
                "screenshot_view_conflict",
                "--quad cannot be combined with individual viewport directions.",
            )
        )

    try:
        settings = load_config()
        resolver, transport = _resolver_and_transport(settings)
        resolved = resolver.resolve(session)
        if info:
            payload = ViewportInfoService(transport).info(resolved)
        else:
            payload = _screenshot_service(settings, transport).capture_viewport(
                resolved,
                views=selected,
                quad=quad,
                scale=scale,
                preset_path=preset,
            )
        emit_result(payload, policy=OutputPolicy.from_config(settings))
    except BridgeError as exc:
        terminate_with_bridge_error(exc)


@capture_app.command("window")
def window_command(
    scale: float = typer.Option(1.0, "--scale"),
    crop: str | None = typer.Option(None, "--crop"),
    preset: Path | None = typer.Option(
        None,
        "--preset",
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
    ),
    session: int | None = typer.Option(None, "--session", min=1),
) -> None:
    try:
        settings = load_config()
        resolver, transport = _resolver_and_transport(settings)
        resolved = resolver.resolve(session)
        payload = _screenshot_service(settings, transport).capture_window(
            resolved,
            scale=scale,
            crop=crop,
            preset_path=preset,
        )
        emit_result(payload, policy=OutputPolicy.from_config(settings))
    except BridgeError as exc:
        terminate_with_bridge_error(exc)


@capture_app.command("ocr")
def ocr_command(
    image: Path = typer.Argument(...),
) -> None:
    try:
        settings = load_config()
        payload = ScreenshotOCRService().recognize(image)
        emit_result(payload, policy=OutputPolicy.from_config(settings))
    except BridgeError as exc:
        terminate_with_bridge_error(exc)

@capture_app.command("turntable")
def turntable_command(
    frames: int = typer.Option(160, "--frames", min=2),
    fps: int = typer.Option(30, "--fps", min=1),
    scale: float = typer.Option(1.0, "--scale"),
    pivot: str = typer.Option(
        "0,0,0",
        "--pivot",
        help="World-space turntable pivot as comma-separated x,y,z coordinates.",
    ),
    distance: float | None = typer.Option(
        None,
        "--distance",
        help="Camera-to-pivot distance in world units.",
    ),
    preset: Path | None = typer.Option(
        None,
        "--preset",
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
    ),
    session: int | None = typer.Option(None, "--session", min=1),
) -> None:
    try:
        settings = load_config()
        parsed_pivot = parse_turntable_pivot(pivot)
        resolver, transport = _resolver_and_transport(settings)
        resolved = resolver.resolve(session)
        payload = _turntable_service(settings, transport).capture(
            resolved,
            frames=frames,
            fps=fps,
            scale=scale,
            pivot=parsed_pivot,
            distance=distance,
            preset_path=preset,
        )
        emit_result(payload, policy=OutputPolicy.from_config(settings))
    except BridgeError as exc:
        terminate_with_bridge_error(exc)
