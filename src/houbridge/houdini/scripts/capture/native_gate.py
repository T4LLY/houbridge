from __future__ import annotations

import ctypes
import json
import os
from pathlib import Path
import sys
import uuid


def _write_result(path: Path, payload: dict[str, object]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )


def _scene_viewers(hou):
    return [
        pane
        for pane in hou.ui.paneTabs()
        if pane.type() == hou.paneTabType.SceneViewer
    ]


def _install_dso(path: Path) -> None:
    library = ctypes.CDLL(str(path))
    install = library.houbridgeInstallCaptureSceneHookGate
    install.argtypes = []
    install.restype = ctypes.c_int
    if install() != 1:
        raise RuntimeError("Native Capture SceneHook registration failed.")

    keepalive = getattr(sys, "_houbridge_capture_native_dsos", None)
    if keepalive is None:
        keepalive = []
        setattr(sys, "_houbridge_capture_native_dsos", keepalive)
    keepalive.append(library)


def _set_environment(values: dict[str, str]):
    previous = {key: os.environ.get(key) for key in values}
    os.environ.update(values)
    return previous


def _restore_environment(previous: dict[str, str | None]) -> None:
    for key, value in previous.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def _run_gate(request: dict[str, object], hou) -> dict[str, object]:
    dso_path = Path(str(request["dso_path"]))
    generation = str(request["generation"])
    gate_path = Path(str(request["gate_path"]))
    flipbook_path = Path(str(request["flipbook_path"]))

    scenes = _scene_viewers(hou)
    if not scenes:
        return {
            "ok": False,
            "code": "capture_native_gate_unavailable",
            "message": "No Scene Viewer pane is available for the native Capture gate.",
        }

    _install_dso(dso_path)
    request_id = uuid.uuid4().hex
    cloned = None
    previous = None
    try:
        # Clone before arming the marker. A clone may redraw while it is created;
        # such a redraw must not satisfy the flipbook-specific gate.
        cloned = scenes[0].clone()
        viewport = cloned.curViewport()
        settings = cloned.flipbookSettings().stash()
        frame = hou.frame()
        settings.frameRange((frame, frame))
        settings.outputToMPlay(False)
        settings.output(str(flipbook_path))
        previous = _set_environment(
            {
                "HOUBRIDGE_CAPTURE_GATE_PATH": str(gate_path),
                "HOUBRIDGE_CAPTURE_GENERATION": generation,
                "HOUBRIDGE_CAPTURE_GATE_REQUEST": request_id,
            }
        )
        cloned.flipbook(viewport, settings)
    finally:
        if previous is not None:
            _restore_environment(previous)
        if cloned is not None:
            try:
                cloned.close()
            except BaseException:
                panel = cloned.floatingPanel()
                if panel is not None:
                    panel.close()

    try:
        observed = gate_path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        observed = ""
    if observed != request_id:
        return {
            "ok": False,
            "code": "capture_native_scenehook_unverified",
            "message": "Scene Viewer flipbook completed without triggering the native Capture SceneHook.",
        }
    return {"ok": True}


def run(request_path: str) -> None:
    path = Path(request_path)
    request = json.loads(path.read_text(encoding="utf-8"))
    result_path = Path(str(request["result_path"]))
    try:
        import hou

        payload = _run_gate(request, hou)
    except BaseException as exc:
        payload = {
            "ok": False,
            "code": "capture_native_gate_failed",
            "message": "Native Capture SceneHook gate failed inside Houdini.",
            "detail": f"{type(exc).__name__}: {exc}"[:4096],
        }
    _write_result(result_path, payload)
