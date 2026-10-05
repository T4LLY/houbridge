from __future__ import annotations

from pathlib import Path
import uuid


def _find_parm(node, *, names, labels):
    for name in names:
        parm = node.parm(name)
        if parm is not None:
            return parm

    wanted = {str(label).casefold() for label in labels}
    for parm in node.parms():
        if parm.parmTemplate().label().casefold() in wanted:
            return parm
    return None


def _set_resolution(rop, resolution) -> None:
    width, height = (int(value) for value in resolution)

    tuple_parm = rop.parmTuple("res")
    if tuple_parm is not None:
        try:
            tuple_parm.set((width, height))
            return
        except BaseException:
            pass

    width_parm = _find_parm(
        rop,
        names=("resx", "width", "xres"),
        labels=("Resolution X", "Width", "X Resolution"),
    )
    height_parm = _find_parm(
        rop,
        names=("resy", "height", "yres"),
        labels=("Resolution Y", "Height", "Y Resolution"),
    )
    if width_parm is None or height_parm is None:
        raise RuntimeError("Flipbook ROP resolution parameters were not found.")
    width_parm.set(width)
    height_parm.set(height)


def create_flipbook_rop(hou, *, camera_path: str, resolution):
    out = hou.node("/out")
    if out is None:
        raise RuntimeError("Expected /out manager was not found.")

    rop = out.createNode(
        "flipbook",
        f"__houbridge_headless_capture_{uuid.uuid4().hex[:8]}",
    )
    try:
        camera_parm = _find_parm(
            rop,
            names=("camera", "camera_path"),
            labels=("Camera",),
        )
        if camera_parm is None:
            raise RuntimeError("Flipbook ROP Camera parameter was not found.")
        camera_parm.set(camera_path)
        _set_resolution(rop, resolution)
        return rop
    except BaseException:
        try:
            rop.destroy()
        except BaseException:
            pass
        raise


def render_flipbook_rop(rop, output_path: Path, hou) -> None:
    output_path.unlink(missing_ok=True)
    frame = hou.frame()
    rop.render(
        frame_range=(frame, frame),
        output_file=str(output_path),
        ignore_inputs=True,
        verbose=True,
        output_progress=True,
    )
    if not output_path.is_file():
        raise RuntimeError("Headless Flipbook ROP did not produce the requested PNG.")


def destroy_flipbook_rop(rop) -> None:
    try:
        rop.destroy()
    except BaseException:
        pass
