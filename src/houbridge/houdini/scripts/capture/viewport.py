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


def _draw_caption(pixmap, label, QtGui):
    painter = QtGui.QPainter(pixmap)
    painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
    size = max(16, min(32, int(round(min(pixmap.width(), pixmap.height()) * 0.045))))
    font = QtGui.QFont("Sans Serif")
    font.setPixelSize(size)
    font.setBold(True)
    path = QtGui.QPainterPath()
    path.addText(12.0, float(size + 12), font, label)
    painter.setPen(QtGui.QPen(QtGui.QColor(0, 0, 0, 230), 4.0))
    painter.setBrush(QtGui.QBrush(QtGui.QColor(255, 255, 255)))
    painter.drawPath(path)
    painter.end()


def _viewport_by_quad_position(scene):
    viewports = list(scene.viewports())
    if len(viewports) != 4:
        raise RuntimeError("Quad layout did not provide four viewports.")
    info = [(viewport, viewport.geometry()) for viewport in viewports]
    top = sorted(info, key=lambda item: item[1][1], reverse=True)[:2]
    bottom = sorted(info, key=lambda item: item[1][1])[:2]
    top = sorted(top, key=lambda item: item[1][0])
    bottom = sorted(bottom, key=lambda item: item[1][0])
    return {
        "top": top[0][0],
        "persp": top[1][0],
        "front": bottom[0][0],
        "right": bottom[1][0],
    }


def capture(request, hou, QtCore, QtGui, QtWidgets):
    runtime = _runtime()
    process_events = runtime["process_events"]
    clone_scene_viewer = runtime["clone_scene_viewer"]
    flipbook_png = runtime["flipbook_png"]
    constrained_size = runtime["constrained_size"]
    flipbook_pixmap = runtime["flipbook_pixmap"]
    save_pixmap = runtime["save_pixmap"]
    apply_preset = runtime["apply_preset"]
    create_attribute_visualizers = runtime["create_attribute_visualizers"]
    destroy_visualizers = runtime["destroy_visualizers"]

    png_paths = [Path(value) for value in request["png_paths"]]
    requested_views = list(request["requested_views"])
    quad = bool(request["quad"])
    scale = float(request["scale"])
    max_width = int(request["max_width"])
    max_height = int(request["max_height"])
    preset = request["preset"]
    view_types = _view_types(hou)

    desktop = hou.ui.curDesktop()
    source_scene = desktop.paneTabOfType(hou.paneTabType.SceneViewer)
    if source_scene is None:
        raise RuntimeError("No Scene Viewer pane is available.")

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
        or quad
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
        if quad:
            scene.setViewportLayout(hou.geometryViewportLayout.Quad)
            process_events(hou, QtWidgets)
            layout = _viewport_by_quad_position(scene)
            labels = ("top", "persp", "front", "right")
            pixmaps = {}
            visualizers = []
            try:
                for label in labels:
                    viewport = layout[label]
                    viewport.changeType(view_types[label])
                    apply_preset(viewport, preset, hou)
                    visualizers.extend(create_attribute_visualizers(viewport, preset, hou))
                process_events(hou, QtWidgets)
                for label in labels:
                    temp_path = png_paths[0].with_name("quad-" + label + ".png")
                    pixmaps[label] = flipbook_pixmap(
                        scene,
                        layout[label],
                        temp_path,
                        hou=hou,
                        QtGui=QtGui,
                    )
            finally:
                destroy_visualizers(visualizers)

            cell_width = max(pixmap.width() for pixmap in pixmaps.values())
            cell_height = max(pixmap.height() for pixmap in pixmaps.values())
            canvas = QtGui.QPixmap(cell_width * 2, cell_height * 2)
            canvas.fill(QtGui.QColor(0, 0, 0))
            painter = QtGui.QPainter(canvas)
            for label, col, row in (
                ("top", 0, 0),
                ("persp", 1, 0),
                ("front", 0, 1),
                ("right", 1, 1),
            ):
                image = pixmaps[label].scaled(
                    cell_width,
                    cell_height,
                    QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                    QtCore.Qt.TransformationMode.SmoothTransformation,
                )
                x = col * cell_width + (cell_width - image.width()) // 2
                y = row * cell_height + (cell_height - image.height()) // 2
                painter.drawPixmap(x, y, image)
            painter.end()
            for label, col, row in (
                ("top", 0, 0),
                ("persp", 1, 0),
                ("front", 0, 1),
                ("right", 1, 1),
            ):
                cell = canvas.copy(col * cell_width, row * cell_height, cell_width, cell_height)
                _draw_caption(cell, label, QtGui)
                painter = QtGui.QPainter(canvas)
                painter.drawPixmap(col * cell_width, row * cell_height, cell)
                painter.end()
            save_pixmap(
                canvas,
                png_paths[0],
                scale=scale,
                max_width=max_width,
                max_height=max_height,
                QtCore=QtCore,
            )
            return

        if not requested_views:
            capture_single_view(scene, scene.curViewport(), png_paths[0])
            return

        scene.setViewportLayout(hou.geometryViewportLayout.Single)
        process_events(hou, QtWidgets)
        viewport = scene.curViewport()
        for index, view_name in enumerate(requested_views):
            viewport.changeType(view_types[view_name])
            process_events(hou, QtWidgets)
            capture_single_view(scene, viewport, png_paths[index])
    finally:
        try:
            scene.close()
        except BaseException:
            panel = scene.floatingPanel()
            if panel is not None:
                panel.close()
