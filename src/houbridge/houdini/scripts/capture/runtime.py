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


def constrained_size(width, height, scale, max_width, max_height):
    scaled_width = max(1, int(round(width * scale)))
    scaled_height = max(1, int(round(height * scale)))
    clamp = min(1.0, max_width / scaled_width, max_height / scaled_height)
    return (
        max(1, int(round(scaled_width * clamp))),
        max(1, int(round(scaled_height * clamp))),
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
