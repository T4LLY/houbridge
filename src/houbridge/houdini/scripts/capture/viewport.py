from __future__ import annotations

import runpy
from pathlib import Path


def _runtime():
    return runpy.run_path(str(Path(__file__).with_name("runtime.py")))


def _view_types(hou):
    return {
        "top": hou.geometryViewportType.Top,
        "bottom": hou.geometryViewportType.Bottom,
        "front": hou.geometryViewportType.Front,
        "back": hou.geometryViewportType.Back,
        "left": hou.geometryViewportType.Left,
        "right": hou.geometryViewportType.Right,
        "persp": hou.geometryViewportType.Perspective,
        "uv": hou.geometryViewportType.UV,
    }


def capture(request, hou, QtCore, QtGui, QtWidgets):
    runtime = _runtime()
    process_events = runtime["process_events"]
    clone_scene_viewer = runtime["clone_scene_viewer"]
    close_scene_viewer = runtime["close_scene_viewer"]
    flipbook_png = runtime["flipbook_png"]
    apply_preset = runtime["apply_preset"]
    create_attribute_visualizers = runtime["create_attribute_visualizers"]
    destroy_visualizers = runtime["destroy_visualizers"]
    resolve_scene_viewer = runtime["resolve_scene_viewer"]

    png_paths = [Path(value) for value in request["png_paths"]]
    requested_views = list(request["requested_views"])
    scale = float(request["scale"])
    max_width = int(request["max_width"])
    max_height = int(request["max_height"])
    preset = request["preset"]
    pane_name = request.get("pane")
    view_types = _view_types(hou)

    source_scene = resolve_scene_viewer(hou, pane_name)

    def capture_single_view(scene, viewport, output_path):
        apply_preset(viewport, preset, hou)
        visualizers = create_attribute_visualizers(viewport, preset, hou)
        try:
            process_events(hou, QtWidgets)
            flipbook_png(
                scene,
                viewport,
                output_path,
                scale=scale,
                max_width=max_width,
                max_height=max_height,
                hou=hou,
                QtCore=QtCore,
                QtGui=QtGui,
            )
        finally:
            destroy_visualizers(visualizers)

    needs_temporary = bool(
        requested_views
        or preset.get("shading")
        or preset.get("overlays")
        or preset.get("attributes")
    )
    if not needs_temporary:
        viewport = source_scene.curViewport()
        flipbook_png(
            source_scene,
            viewport,
            png_paths[0],
            scale=scale,
            max_width=max_width,
            max_height=max_height,
            hou=hou,
            QtCore=QtCore,
            QtGui=QtGui,
        )
        return

    scene = clone_scene_viewer(source_scene, hou, QtWidgets)
    try:
        if not requested_views:
            capture_single_view(scene, scene.curViewport(), png_paths[0])
            return

        scene.setViewportLayout(hou.geometryViewportLayout.Single)
        process_events(hou, QtWidgets)
        viewport = scene.curViewport()
        for index, view_name in enumerate(requested_views):
            viewport.changeType(view_types[view_name])
            process_events(hou, QtWidgets)
            viewport.frameAll()
            process_events(hou, QtWidgets)
            capture_single_view(scene, viewport, png_paths[index])
    finally:
        close_scene_viewer(scene)
