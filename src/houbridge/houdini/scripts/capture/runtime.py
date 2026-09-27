from __future__ import annotations


SHADING_NAMES = {
    "wire": "Wire",
    "wireghost": "WireGhost",
    "hiddenline": "HiddenLineInvisible",
    "hiddenlineghost": "HiddenLineGhost",
    "flat": "Flat",
    "flatwire": "FlatWire",
    "smooth": "Smooth",
    "smoothwire": "SmoothWire",
    "matcap": "MatCap",
    "matcapwire": "MatCapWire",
}

OVERLAY_METHODS = {
    "point_markers": "showPointMarkers",
    "point_numbers": "showPointNumbers",
    "point_normals": "showPointNormals",
    "point_uvs": "showPointUVs",
    "point_positions": "showPointPositions",
    "prim_numbers": "showPrimNumbers",
    "prim_normals": "showPrimNormals",
    "vertex_markers": "showVertexMarkers",
    "vertex_numbers": "showVertexNumbers",
    "vertex_normals": "showVertexNormals",
    "vertex_uvs": "showVertexUVs",
    "uv_backfaces": "showUVBackfaces",
    "uv_overlap": "showUVOverlap",
}

ATTR_CLASSES = {
    "point": "points",
    "prim": "primitives",
    "vertex": "vertices",
    "detail": "detail",
}


class CaptureRequestError(RuntimeError):
    def __init__(self, code, message, *, context=None):
        super().__init__(message)
        self.code = code
        self.context = dict(context) if context else None


def list_scene_viewers(hou):
    return tuple(
        pane_tab
        for pane_tab in hou.ui.paneTabs()
        if pane_tab.type() == hou.paneTabType.SceneViewer
    )


def _viewport_type_name(viewport, hou):
    names = {
        hou.geometryViewportType.Top: "top",
        hou.geometryViewportType.Bottom: "bottom",
        hou.geometryViewportType.Front: "front",
        hou.geometryViewportType.Back: "back",
        hou.geometryViewportType.Left: "left",
        hou.geometryViewportType.Right: "right",
        hou.geometryViewportType.Perspective: "persp",
        hou.geometryViewportType.UV: "uv",
    }
    return names.get(
        viewport.type(),
        str(viewport.type()).rsplit(".", 1)[-1].lower(),
    )


def _scene_current_node_path(scene):
    try:
        node = scene.currentNode()
        return None if node is None else node.path()
    except BaseException:
        return None


def describe_scene_viewer(scene, hou):
    viewports = []
    for viewport in scene.viewports():
        if not viewport.isVisible():
            continue
        _x, _y, width, height = viewport.geometry()
        viewports.append(
            {
                "name": viewport.name(),
                "type": _viewport_type_name(viewport, hou),
                "width": int(width),
                "height": int(height),
            }
        )
    return {
        "name": scene.name(),
        "current_node": _scene_current_node_path(scene),
        "viewports": viewports,
    }


def describe_scene_viewers(scenes, hou):
    return {
        "panes": [describe_scene_viewer(scene, hou) for scene in scenes],
    }


def resolve_scene_viewer(hou, pane_name=None):
    scenes = list_scene_viewers(hou)
    if not scenes:
        raise CaptureRequestError(
            "viewport_unavailable",
            "No Scene Viewer pane is available.",
        )

    if pane_name is None:
        if len(scenes) == 1:
            return scenes[0]
        raise CaptureRequestError(
            "scene_viewer_ambiguous",
            "Multiple Scene Viewer panes are available; specify --pane.",
            context=describe_scene_viewers(scenes, hou),
        )

    matches = tuple(scene for scene in scenes if scene.name() == pane_name)
    if len(matches) == 1:
        return matches[0]
    context = describe_scene_viewers(scenes, hou)
    if not matches:
        raise CaptureRequestError(
            "scene_viewer_not_found",
            f"Scene Viewer pane {pane_name!r} was not found.",
            context=context,
        )
    raise CaptureRequestError(
        "scene_viewer_ambiguous",
        f"Multiple Scene Viewer panes named {pane_name!r} are available.",
        context=context,
    )


def constrained_size(width, height, scale, max_width, max_height):
    scaled_width = max(1, int(round(width * scale)))
    scaled_height = max(1, int(round(height * scale)))
    clamp = min(1.0, max_width / scaled_width, max_height / scaled_height)
    return (
        max(1, int(round(scaled_width * clamp))),
        max(1, int(round(scaled_height * clamp))),
    )




def _resize_pixmap(pixmap, *, scale, max_width, max_height, QtCore):
    width, height = constrained_size(
        pixmap.width(),
        pixmap.height(),
        scale,
        max_width,
        max_height,
    )
    if width == pixmap.width() and height == pixmap.height():
        return pixmap
    return pixmap.scaled(
        width,
        height,
        QtCore.Qt.AspectRatioMode.KeepAspectRatio,
        QtCore.Qt.TransformationMode.SmoothTransformation,
    )


def save_pixmap(pixmap, path, *, scale, max_width, max_height, QtCore):
    final = _resize_pixmap(
        pixmap,
        scale=scale,
        max_width=max_width,
        max_height=max_height,
        QtCore=QtCore,
    )
    if not final.save(str(path), "PNG"):
        raise RuntimeError("Qt failed to save capture PNG.")


def flipbook_pixmap(scene, viewport, path, *, hou, QtGui):
    settings = scene.flipbookSettings().stash()
    frame = hou.frame()
    settings.frameRange((frame, frame))
    settings.outputToMPlay(False)
    settings.output(str(path))
    scene.flipbook(viewport, settings)
    if not path.is_file():
        raise RuntimeError("Viewport flipbook did not produce a PNG.")
    pixmap = QtGui.QPixmap(str(path))
    if pixmap.isNull():
        raise RuntimeError("Qt failed to load viewport flipbook PNG.")
    path.unlink(missing_ok=True)
    return pixmap


def flipbook_png(
    scene,
    viewport,
    path,
    *,
    scale,
    max_width,
    max_height,
    hou,
    QtCore,
    QtGui,
):
    pixmap = flipbook_pixmap(scene, viewport, path, hou=hou, QtGui=QtGui)
    save_pixmap(
        pixmap,
        path,
        scale=scale,
        max_width=max_width,
        max_height=max_height,
        QtCore=QtCore,
    )

def process_events(hou, QtWidgets):
    QtWidgets.QApplication.processEvents()
    hou.ui.triggerUpdate()
    QtWidgets.QApplication.processEvents()


def clone_scene_viewer(source_scene, hou, QtWidgets):
    cloned = source_scene.clone()
    try:
        source_rect = source_scene.qtScreenGeometry()
        window = cloned.qtParentWindow()
        if window is not None:
            window.resize(max(320, source_rect.width()), max(240, source_rect.height()))
    except BaseException:
        pass
    process_events(hou, QtWidgets)
    return cloned


def apply_preset(viewport, preset, hou):
    settings = viewport.settings()
    shading = preset.get("shading")
    overlays = preset.get("overlays") or {}
    display_sets = (
        hou.displaySetType.SceneObject,
        hou.displaySetType.SelectedObject,
        hou.displaySetType.GhostObject,
        hou.displaySetType.DisplayModel,
        hou.displaySetType.CurrentModel,
        hou.displaySetType.TemplateModel,
    )
    for display_type in display_sets:
        display = settings.displaySet(display_type)
        display.setUniqueDisplaySet(True)
        if shading:
            display.setShadedMode(getattr(hou.glShadingType, SHADING_NAMES[shading]))
        for name, enabled in overlays.items():
            getattr(display, OVERLAY_METHODS[name])(bool(enabled))


def create_attribute_visualizers(viewport, preset, hou):
    attributes = preset.get("attributes") or []
    if not attributes:
        return []
    import soputils

    visualizers = []
    marker_type = hou.viewportVisualizers.type("vis_marker")
    if marker_type is None:
        raise RuntimeError("Houdini marker visualizer type is unavailable.")
    hou.viewportVisualizers.setIsCategoryActive(
        True,
        hou.viewportVisualizerCategory.Common,
        viewport=viewport,
    )
    for item in attributes:
        visualizer = hou.viewportVisualizers.createVisualizer(
            marker_type,
            hou.viewportVisualizerCategory.Common,
        )
        visualizer.setLabel(item["name"])
        soputils.setupVisualizer(visualizer, item["name"], ATTR_CLASSES[item["class"]])
        visualizer.setIsActive(True, viewport)
        visualizers.append(visualizer)
    return visualizers


def destroy_visualizers(visualizers):
    for visualizer in reversed(visualizers):
        try:
            visualizer.destroy()
        except BaseException:
            pass
