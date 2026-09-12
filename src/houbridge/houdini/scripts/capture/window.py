from __future__ import annotations

import json
import runpy
from pathlib import Path


def _runtime():
    return runpy.run_path(str(Path(__file__).with_name("runtime.py")))


def _pane_type_name(pane_tab, hou):
    pane_type = pane_tab.type()
    if pane_type == hou.paneTabType.SceneViewer:
        return "scene_viewer"
    if pane_type == hou.paneTabType.NetworkEditor:
        return "network_editor"
    if pane_type == hou.paneTabType.Parm:
        return "parameter_editor"
    return str(pane_type).rsplit(".", 1)[-1].lower()


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
    return names.get(viewport.type(), str(viewport.type()).rsplit(".", 1)[-1].lower())


def _scaled_rect(x, y, width, height, sx, sy, out_width, out_height):
    x1 = max(0, min(out_width, int(round(x * sx))))
    y1 = max(0, min(out_height, int(round(y * sy))))
    x2 = max(x1, min(out_width, int(round((x + width) * sx))))
    y2 = max(y1, min(out_height, int(round((y + height) * sy))))
    return {"x": x1, "y": y1, "width": x2 - x1, "height": y2 - y1}


def _rect_intersection(rect, crop):
    left = max(rect["x"], crop["x"])
    top = max(rect["y"], crop["y"])
    right = min(rect["x"] + rect["width"], crop["x"] + crop["width"])
    bottom = min(rect["y"] + rect["height"], crop["y"] + crop["height"])
    if right <= left or bottom <= top:
        return None
    return {"x": left, "y": top, "width": right - left, "height": bottom - top}


def _split_index(selector):
    base, separator, suffix = selector.rpartition(":")
    if separator and suffix.isdigit():
        return base, int(suffix)
    return selector, None


def _choose_crop_candidate(selector, areas):
    pane_exact = [area for area in areas if area["name"] == selector]
    if len(pane_exact) == 1:
        return pane_exact[0]

    if selector.startswith("viewport:"):
        token = selector[len("viewport:") :]
        key, index = _split_index(token)
        candidates = []
        for area in areas:
            for viewport in area.get("viewports", []):
                if viewport["type"] == key or viewport["name"] == key:
                    candidates.append(viewport)
    else:
        key, index = _split_index(selector)
        candidates = [area for area in areas if area["type"] == key or area["name"] == key]

    if index is not None:
        if index < len(candidates):
            return candidates[index]
        raise RuntimeError("Screenshot crop selector index is out of range: " + selector)
    if not candidates:
        raise RuntimeError("Screenshot crop target was not found: " + selector)
    if len(candidates) > 1:
        raise RuntimeError("Screenshot crop target is ambiguous; append :0, :1, ...: " + selector)
    return candidates[0]


def _translate_and_scale_rect(rect, crop_rect, sx, sy, out_width, out_height):
    intersection = _rect_intersection(rect, crop_rect)
    if intersection is None:
        return None
    return _scaled_rect(
        intersection["x"] - crop_rect["x"],
        intersection["y"] - crop_rect["y"],
        intersection["width"],
        intersection["height"],
        sx,
        sy,
        out_width,
        out_height,
    )


def _finalize_areas(source_areas, crop_rect, sx, sy, out_width, out_height):
    result = []
    for source_area in source_areas:
        rect = _translate_and_scale_rect(source_area, crop_rect, sx, sy, out_width, out_height)
        if rect is None:
            continue
        area = {"type": source_area["type"], "name": source_area["name"], **rect}
        if "viewports" in source_area:
            viewports = []
            for source_viewport in source_area["viewports"]:
                viewport_rect = _translate_and_scale_rect(
                    source_viewport,
                    crop_rect,
                    sx,
                    sy,
                    out_width,
                    out_height,
                )
                if viewport_rect is not None:
                    viewports.append(
                        {
                            "type": source_viewport["type"],
                            "name": source_viewport["name"],
                            **viewport_rect,
                        }
                    )
            area["viewports"] = viewports
        result.append(area)
    return result


def capture(request, hou, QtCore, _QtGui, QtWidgets):
    runtime = _runtime()
    process_events = runtime["process_events"]
    constrained_size = runtime["constrained_size"]

    png_path = Path(request["png_paths"][0])
    bounds_path_value = request.get("bounds_path")
    if not bounds_path_value:
        raise RuntimeError("Window bounds output path is missing.")
    bounds_path = Path(bounds_path_value)
    scale = float(request["scale"])
    max_width = int(request["max_width"])
    max_height = int(request["max_height"])
    crop_selector = (request.get("preset") or {}).get("crop")

    window = hou.qt.mainWindow()
    if window is None:
        raise RuntimeError("Houdini main window is unavailable.")

    process_events(hou, QtWidgets)
    pixmap = window.grab()
    if pixmap.isNull():
        raise RuntimeError("Qt failed to capture the main window.")
    full_source_width = pixmap.width()
    full_source_height = pixmap.height()
    logical_width = max(1, window.width())
    logical_height = max(1, window.height())
    logical_to_source_x = full_source_width / logical_width
    logical_to_source_y = full_source_height / logical_height
    origin = window.mapToGlobal(QtCore.QPoint(0, 0))

    source_areas = []
    for pane_tab in hou.ui.currentPaneTabs():
        try:
            pane_window = pane_tab.qtParentWindow()
            if pane_window is None:
                continue
            try:
                if int(pane_window.winId()) != int(window.winId()):
                    continue
            except BaseException:
                if pane_window is not window:
                    continue
            rect = pane_tab.qtScreenGeometry()
            rel_x = rect.x() - origin.x()
            rel_y = rect.y() - origin.y()
            if (
                rel_x >= logical_width
                or rel_y >= logical_height
                or rel_x + rect.width() <= 0
                or rel_y + rect.height() <= 0
            ):
                continue
            area = {
                "type": _pane_type_name(pane_tab, hou),
                "name": pane_tab.name(),
                **_scaled_rect(
                    rel_x,
                    rel_y,
                    rect.width(),
                    rect.height(),
                    logical_to_source_x,
                    logical_to_source_y,
                    full_source_width,
                    full_source_height,
                ),
            }
            if pane_tab.type() == hou.paneTabType.SceneViewer:
                viewport_entries = []
                for viewport in pane_tab.viewports():
                    if not viewport.isVisible():
                        continue
                    vx, vy, vw, vh = viewport.geometry()
                    top_y = rect.height() - (vy + vh)
                    viewport_entries.append(
                        {
                            "type": _viewport_type_name(viewport, hou),
                            "name": viewport.name(),
                            **_scaled_rect(
                                rel_x + vx,
                                rel_y + top_y,
                                vw,
                                vh,
                                logical_to_source_x,
                                logical_to_source_y,
                                full_source_width,
                                full_source_height,
                            ),
                        }
                    )
                area["viewports"] = viewport_entries
            source_areas.append(area)
        except BaseException:
            continue

    crop_rect = {
        "x": 0,
        "y": 0,
        "width": full_source_width,
        "height": full_source_height,
    }
    if crop_selector:
        selected = _choose_crop_candidate(str(crop_selector), source_areas)
        crop_rect = {
            "x": int(selected["x"]),
            "y": int(selected["y"]),
            "width": int(selected["width"]),
            "height": int(selected["height"]),
        }
        if crop_rect["width"] <= 0 or crop_rect["height"] <= 0:
            raise RuntimeError("Screenshot crop target has no visible pixels: " + str(crop_selector))
        pixmap = pixmap.copy(
            crop_rect["x"],
            crop_rect["y"],
            crop_rect["width"],
            crop_rect["height"],
        )

    crop_source_width = pixmap.width()
    crop_source_height = pixmap.height()
    final_width, final_height = constrained_size(
        crop_source_width,
        crop_source_height,
        scale,
        max_width,
        max_height,
    )
    if final_width != crop_source_width or final_height != crop_source_height:
        pixmap = pixmap.scaled(
            final_width,
            final_height,
            QtCore.Qt.AspectRatioMode.KeepAspectRatio,
            QtCore.Qt.TransformationMode.SmoothTransformation,
        )
    final_width = pixmap.width()
    final_height = pixmap.height()
    source_to_final_x = final_width / crop_source_width
    source_to_final_y = final_height / crop_source_height
    areas = _finalize_areas(
        source_areas,
        crop_rect,
        source_to_final_x,
        source_to_final_y,
        final_width,
        final_height,
    )

    if not pixmap.save(str(png_path), "PNG"):
        raise RuntimeError("Qt failed to save the main-window screenshot.")

    bounds = {
        "width": final_width,
        "height": final_height,
        "coordinate_space": "final_png_top_left",
        "source_width": crop_source_width,
        "source_height": crop_source_height,
        "scale_x": source_to_final_x,
        "scale_y": source_to_final_y,
        "areas": areas,
    }
    if crop_selector:
        bounds["cropped_from"] = str(crop_selector)
    bounds_path.write_text(
        json.dumps(bounds, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
