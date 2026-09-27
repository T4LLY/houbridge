from __future__ import annotations

import json
import runpy
import traceback
from pathlib import Path


def _runtime():
    return runpy.run_path(str(Path(__file__).with_name("runtime.py")))


def _orbit_rotation(angle_degrees, hou):
    return hou.hmath.buildRotateAboutAxis(
        hou.Vector3((0.0, 1.0, 0.0)),
        angle_degrees,
    ).extractRotationMatrix3()


def capture(request, hou, QtCore, QtGui, QtWidgets):
    runtime = _runtime()
    process_events = runtime["process_events"]
    clone_scene_viewer = runtime["clone_scene_viewer"]
    close_scene_viewer = runtime["close_scene_viewer"]
    apply_preset = runtime["apply_preset"]
    create_attribute_visualizers = runtime["create_attribute_visualizers"]
    destroy_visualizers = runtime["destroy_visualizers"]
    flipbook_png = runtime["flipbook_png"]

    frames = int(request["frames"])
    frames_dir = Path(request["frames_dir"])
    scale = float(request["scale"])
    pivot = hou.Vector3(request["pivot"])
    distance_value = request["distance"]
    max_width = int(request["max_width"])
    max_height = int(request["max_height"])
    preset = request["preset"]

    source_scene = hou.ui.curDesktop().paneTabOfType(hou.paneTabType.SceneViewer)
    if source_scene is None:
        raise RuntimeError("No Scene Viewer pane is available.")
    source_viewport = source_scene.curViewport()
    if source_viewport.type() != hou.geometryViewportType.Perspective:
        source_viewport = next(
            (
                viewport
                for viewport in source_scene.viewports()
                if viewport.type() == hou.geometryViewportType.Perspective
            ),
            None,
        )
    if source_viewport is None:
        raise RuntimeError("No Perspective viewport is available for turntable capture.")

    source_world_position = source_viewport.viewTransform().extractTranslates()
    source_camera = source_viewport.defaultCamera().stash()
    offset = hou.Vector3(source_world_position) - pivot
    if offset.length() <= 1e-9:
        raise RuntimeError(
            "Perspective viewport camera is located at the requested turntable pivot."
        )
    if distance_value is not None:
        offset = offset * (float(distance_value) / offset.length())

    scene = clone_scene_viewer(source_scene, hou, QtWidgets)
    visualizers = []
    try:
        scene.setViewportLayout(hou.geometryViewportLayout.Single)
        process_events(hou, QtWidgets)
        viewport = scene.curViewport()
        viewport.changeType(hou.geometryViewportType.Perspective)
        viewport.useDefaultCamera()
        viewport.setDefaultCamera(source_camera.stash())
        apply_preset(viewport, preset, hou)
        visualizers = create_attribute_visualizers(viewport, preset, hou)
        process_events(hou, QtWidgets)

        for index in range(frames):
            # Negative world-Y rotation is clockwise when viewed from +Y.
            angle = -360.0 * float(index) / float(frames)
            rotated_offset = offset * _orbit_rotation(angle, hou)
            position = pivot + rotated_offset
            backward = rotated_offset.normalized()
            up_hint = hou.Vector3((0.0, 1.0, 0.0))
            right = up_hint.cross(backward)
            if right.length() <= 1e-9:
                up_hint = hou.Vector3((0.0, 0.0, 1.0))
                right = up_hint.cross(backward)
            right = right.normalized()
            camera_up = backward.cross(right).normalized()
            rotation = hou.Matrix3(
                (
                    tuple(right),
                    tuple(camera_up),
                    tuple(backward),
                )
            ).transposed()

            frame_camera = source_camera.stash()
            frame_camera.setPivot(tuple(pivot))
            frame_camera.setRotation(rotation)
            camera_translation = (position - pivot) * rotation
            frame_camera.setTranslation(tuple(camera_translation))
            viewport.setDefaultCamera(frame_camera)
            process_events(hou, QtWidgets)
            flipbook_png(
                scene,
                viewport,
                frames_dir / f"frame{index + 1:04d}.png",
                scale=scale,
                max_width=max_width,
                max_height=max_height,
                hou=hou,
                QtCore=QtCore,
                QtGui=QtGui,
            )
    finally:
        destroy_visualizers(visualizers)
        close_scene_viewer(scene)


def run(request_path: str) -> None:
    import hou
    from PySide6 import QtCore, QtGui, QtWidgets

    request = json.loads(Path(request_path).read_text(encoding="utf-8"))
    result_path = Path(request["result_path"])
    try:
        capture(request, hou, QtCore, QtGui, QtWidgets)
        payload = {"ok": True}
    except BaseException as exc:
        payload = {
            "ok": False,
            "message": str(exc) or type(exc).__name__,
            "detail": traceback.format_exc(),
        }
    result_path.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
