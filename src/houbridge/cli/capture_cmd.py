from __future__ import annotations

from pathlib import Path

import typer

from houbridge.capture import (
    CameraService,
    CaptureArtifactPublisher,
    NativeAnalysisCaptureBackend,
    NativeCaptureBuilder,
    ScreenshotService,
    TurntableService,
    ViewportInfoService,
    build_analysis_request,
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
    help="Capture or inspect Houdini views and cameras.",
)


def _resolver_and_transport(settings: HoubridgeConfig) -> tuple[SessionResolver, HoudiniTransport]:
    paths = GlobalDataPaths.from_data_dir(settings.storage.data_dir)
    registry = SessionRegistry(paths.sessions_registry)
    transport = HoudiniTransport.from_config(settings.houdini)
    probe = SessionProbe(lambda: transport)
    return SessionResolver(registry, probe), transport


def _analysis_backend(
    settings: HoubridgeConfig,
    transport: HoudiniTransport,
) -> NativeAnalysisCaptureBackend:
    paths = GlobalDataPaths.from_data_dir(settings.storage.data_dir)
    return NativeAnalysisCaptureBackend(
        transport,
        NativeCaptureBuilder(paths.capture_native_directory),
    )


def _screenshot_service(
    settings: HoubridgeConfig,
    transport: HoudiniTransport,
) -> ScreenshotService:
    publisher = CaptureArtifactPublisher(
        TemporaryArtifactService(),
        settings.screenshot.retention_hours,
        lock_timeout_seconds=settings.houdini.lock_timeout_seconds,
    )
    return ScreenshotService(
        transport,
        settings.screenshot,
        publisher,
        analysis_backend=_analysis_backend(settings, transport),
    )


def _turntable_service(
    settings: HoubridgeConfig,
    transport: HoudiniTransport,
) -> TurntableService:
    publisher = CaptureArtifactPublisher(
        TemporaryArtifactService(),
        settings.screenshot.retention_hours,
        lock_timeout_seconds=settings.houdini.lock_timeout_seconds,
    )
    return TurntableService(
        transport,
        settings.screenshot,
        publisher,
    )


def _camera_service(
    settings: HoubridgeConfig,
    transport: HoudiniTransport,
) -> CameraService:
    publisher = CaptureArtifactPublisher(
        TemporaryArtifactService(),
        settings.screenshot.retention_hours,
        lock_timeout_seconds=settings.houdini.lock_timeout_seconds,
    )
    return CameraService(
        transport,
        settings.screenshot,
        publisher,
        analysis_backend=_analysis_backend(settings, transport),
    )


def _scene_viewer_catalog(
    settings: HoubridgeConfig,
    session: int | None,
) -> dict[str, object]:
    resolver, transport = _resolver_and_transport(settings)
    resolved = resolver.resolve(session)
    return ViewportInfoService(transport).info(resolved)


@capture_app.command("panes", help="List Scene Viewer panes usable with --pane.")
def panes_command(
    session: int | None = typer.Option(
        None,
        "--session",
        min=1,
        help="Target this registered session instead of the primary session.",
    ),
) -> None:
    try:
        settings = load_config()
        payload = _scene_viewer_catalog(settings, session)
        emit_result(payload, policy=OutputPolicy.from_config(settings))
    except BridgeError as exc:
        terminate_with_bridge_error(exc)


@capture_app.command("viewport", help="Capture a Scene Viewer viewport.")
def viewport_command(
    info: bool = typer.Option(
        False,
        "--info",
        help="List available Scene Viewer panes and viewports instead of capturing.",
    ),
    top: bool = typer.Option(False, "--top", help="Capture the top view."),
    bottom: bool = typer.Option(False, "--bottom", help="Capture the bottom view."),
    front: bool = typer.Option(False, "--front", help="Capture the front view."),
    back: bool = typer.Option(False, "--back", help="Capture the back view."),
    left: bool = typer.Option(False, "--left", help="Capture the left view."),
    right: bool = typer.Option(False, "--right", help="Capture the right view."),
    persp: bool = typer.Option(False, "--persp", help="Capture the perspective view."),
    uv: bool = typer.Option(False, "--uv", help="Capture the UV view."),
    scale: float = typer.Option(
        1.0,
        "--scale",
        help="Scale the captured image dimensions by this factor.",
    ),
    preset: Path | None = typer.Option(
        None,
        "--preset",
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
        help="Apply settings from a screenshot preset JSON file.",
    ),
    pane: str | None = typer.Option(
        None,
        "--pane",
        help="Capture from this Scene Viewer pane-tab name.",
    ),
    capture_pass: str = typer.Option(
        "beauty",
        "--pass",
        help="Render beauty, depth, grid, normal, object-id, or curvature.",
    ),
    model: list[str] | None = typer.Option(
        None,
        "--model",
        help="Filter a non-beauty pass to this OBJ path; repeat as needed.",
    ),
    unit: float | None = typer.Option(
        None,
        "--unit",
        help="World-space grid spacing; required with --pass grid.",
    ),
    curvature_scale: float | None = typer.Option(
        None,
        "--curvature-scale",
        help="Curvature response multiplier; valid only with --pass curvature.",
    ),
    curvature_colormap: str | None = typer.Option(
        None,
        "--curvature-colormap",
        help="Curvature colormap gray or rg; valid only with --pass curvature.",
    ),
    session: int | None = typer.Option(
        None,
        "--session",
        min=1,
        help="Target this registered session instead of the primary session.",
    ),
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
    analysis_options_selected = (
        capture_pass.strip().lower() != "beauty"
        or bool(model)
        or unit is not None
        or curvature_scale is not None
        or curvature_colormap is not None
    )
    if info and (
        selected
        or scale != 1.0
        or preset is not None
        or pane is not None
        or analysis_options_selected
    ):
        terminate_with_bridge_error(
            BridgeError(
                "capture_info_conflict",
                "--info cannot be combined with viewport capture options.",
            )
        )
    try:
        settings = load_config()
        if info:
            payload = _scene_viewer_catalog(settings, session)
        else:
            analysis = build_analysis_request(
                capture_pass,
                model_paths=tuple(model or ()),
                unit=unit,
                curvature_scale=curvature_scale,
                curvature_colormap=curvature_colormap,
            )
            resolver, transport = _resolver_and_transport(settings)
            resolved = resolver.resolve(session)
            capture_kwargs = {
                "views": selected,
                "scale": scale,
                "preset_path": preset,
                "pane": pane,
            }
            if analysis is not None:
                capture_kwargs["analysis"] = analysis
            payload = _screenshot_service(settings, transport).capture_viewport(
                resolved,
                **capture_kwargs,
            )
        emit_result(payload, policy=OutputPolicy.from_config(settings))
    except BridgeError as exc:
        terminate_with_bridge_error(exc)


@capture_app.command("camera", help="Capture through an OBJ or SOP camera, or inspect cameras.")
def camera_command(
    camera_path: str | None = typer.Argument(
        None,
        metavar="CAMERA_PATH",
        help="Absolute OBJ or SOP camera path.",
    ),
    list_cameras: bool = typer.Option(
        False,
        "--list",
        help="List supported OBJ and Camera SOP cameras without capturing.",
    ),
    detail: bool = typer.Option(
        False,
        "--detail",
        help="Show bounded details for CAMERA_PATH without capturing.",
    ),
    scale: float = typer.Option(
        1.0,
        "--scale",
        help="Scale the camera resolution by this factor.",
    ),
    pane: str | None = typer.Option(
        None,
        "--pane",
        help="Capture from this Scene Viewer pane-tab name.",
    ),
    capture_pass: str = typer.Option(
        "beauty",
        "--pass",
        help="Render beauty, depth, grid, normal, object-id, or curvature.",
    ),
    model: list[str] | None = typer.Option(
        None,
        "--model",
        help="Filter a non-beauty pass to this OBJ path; repeat as needed.",
    ),
    unit: float | None = typer.Option(
        None,
        "--unit",
        help="World-space grid spacing; required with --pass grid.",
    ),
    curvature_scale: float | None = typer.Option(
        None,
        "--curvature-scale",
        help="Curvature response multiplier; valid only with --pass curvature.",
    ),
    curvature_colormap: str | None = typer.Option(
        None,
        "--curvature-colormap",
        help="Curvature colormap gray or rg; valid only with --pass curvature.",
    ),
    session: int | None = typer.Option(
        None,
        "--session",
        min=1,
        help="Target this registered session instead of the primary session.",
    ),
) -> None:
    analysis_options_selected = (
        capture_pass.strip().lower() != "beauty"
        or bool(model)
        or unit is not None
        or curvature_scale is not None
        or curvature_colormap is not None
    )
    if list_cameras and (
        camera_path is not None
        or detail
        or scale != 1.0
        or pane is not None
        or analysis_options_selected
    ):
        terminate_with_bridge_error(
            BridgeError(
                "capture_camera_list_conflict",
                "--list cannot be combined with camera capture options.",
            )
        )
    if detail and (
        scale != 1.0
        or pane is not None
        or analysis_options_selected
    ):
        terminate_with_bridge_error(
            BridgeError(
                "capture_camera_detail_conflict",
                "--detail cannot be combined with camera capture options.",
            )
        )
    if not list_cameras and camera_path is None:
        terminate_with_bridge_error(
            BridgeError(
                "camera_path_required",
                "CAMERA_PATH is required unless --list is used.",
            )
        )

    try:
        settings = load_config()
        analysis = None
        if not list_cameras and not detail:
            analysis = build_analysis_request(
                capture_pass,
                model_paths=tuple(model or ()),
                unit=unit,
                curvature_scale=curvature_scale,
                curvature_colormap=curvature_colormap,
            )
        resolver, transport = _resolver_and_transport(settings)
        resolved = resolver.resolve(session)
        service = _camera_service(settings, transport)
        if list_cameras:
            payload = service.list(resolved)
        elif detail:
            payload = service.detail(resolved, camera_path)
        else:
            capture_kwargs = {
                "scale": scale,
                "pane": pane,
            }
            if analysis is not None:
                capture_kwargs["analysis"] = analysis
            payload = service.capture(
                resolved,
                camera_path,
                **capture_kwargs,
            )
        emit_result(payload, policy=OutputPolicy.from_config(settings))
    except BridgeError as exc:
        terminate_with_bridge_error(exc)


@capture_app.command("window", help="Capture a Houdini window image.")
def window_command(
    scale: float = typer.Option(
        1.0,
        "--scale",
        help="Scale the captured image dimensions by this factor.",
    ),
    crop: str | None = typer.Option(
        None,
        "--crop",
        help="Crop to a pane or viewport selector; append :N when ambiguous.",
    ),
    preset: Path | None = typer.Option(
        None,
        "--preset",
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
        help="Apply settings from a screenshot preset JSON file.",
    ),
    session: int | None = typer.Option(
        None,
        "--session",
        min=1,
        help="Target this registered session instead of the primary session.",
    ),
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


@capture_app.command("turntable", help="Capture a Scene Viewer turntable animation.")
def turntable_command(
    frames: int = typer.Option(
        160,
        "--frames",
        min=2,
        help="Number of frames in one full rotation.",
    ),
    fps: int = typer.Option(
        30,
        "--fps",
        min=1,
        help="Frame rate of the encoded turntable video.",
    ),
    scale: float = typer.Option(
        1.0,
        "--scale",
        help="Scale each captured frame by this factor.",
    ),
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
        help="Apply shading, overlay, and attribute preset settings.",
    ),
    pane: str | None = typer.Option(
        None,
        "--pane",
        help="Capture from this Scene Viewer pane-tab name.",
    ),
    session: int | None = typer.Option(
        None,
        "--session",
        min=1,
        help="Target this registered session instead of the primary session.",
    ),
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
            pane=pane,
        )
        emit_result(payload, policy=OutputPolicy.from_config(settings))
    except BridgeError as exc:
        terminate_with_bridge_error(exc)
