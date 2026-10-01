from __future__ import annotations

import json
import traceback
from pathlib import Path


def _state(hou: object) -> dict[str, object]:
    return {
        "path": str(hou.hipFile.path()),  # type: ignore[attr-defined]
        "dirty": bool(hou.hipFile.hasUnsavedChanges()),  # type: ignore[attr-defined]
        "new": bool(hou.hipFile.isNewFile()),  # type: ignore[attr-defined]
    }


def run(request_path: str) -> None:
    import hou

    request = json.loads(Path(request_path).read_text(encoding="utf-8"))
    output_path = Path(request["output_path"])
    mode = request.get("mode")

    try:
        if mode == "info":
            payload = {"ok": True, **_state(hou)}
        elif mode == "save":
            if bool(hou.hipFile.isNewFile()):
                payload = {
                    "ok": False,
                    "code": "hip_save_target_missing",
                    "message": "Current HIP file has no established save target.",
                }
            else:
                if bool(hou.hipFile.hasUnsavedChanges()):
                    hou.hipFile.save()
                    status = "saved"
                else:
                    status = "unchanged"
                payload = {
                    "ok": True,
                    "path": str(hou.hipFile.path()),
                    "status": status,
                }
        else:
            raise RuntimeError(f"Unsupported HIP operation: {mode!r}")
    except BaseException as exc:
        payload = {
            "ok": False,
            "code": "hip_save_failed" if mode == "save" else "hip_info_failed",
            "message": str(exc) or type(exc).__name__,
            "detail": traceback.format_exc(),
        }

    staging = output_path.with_suffix(".json.tmp")
    staging.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    staging.replace(output_path)
