from __future__ import annotations

import json
import traceback
from pathlib import Path


def _write_result(path: Path, payload: dict[str, object]) -> None:
    staging = path.with_suffix(".json.tmp")
    staging.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    staging.replace(path)


def run(request_path: str) -> None:
    import hou

    request = json.loads(Path(request_path).read_text(encoding="utf-8"))
    output_path = Path(request["output_path"])

    try:
        hip_path = str(hou.hipFile.path())
        discard = request.get("discard") is True
        if not discard and not bool(hou.isUIAvailable()):
            _write_result(
                output_path,
                {
                    "ok": False,
                    "code": "session_dirty_state_unavailable",
                    "message": (
                        "Cannot safely determine unsaved HIP changes for a "
                        "non-graphical Houdini session."
                    ),
                    "detail": f"path={hip_path}",
                },
            )
            return

        if not discard and bool(hou.hipFile.hasUnsavedChanges()):
            _write_result(
                output_path,
                {
                    "ok": False,
                    "code": "session_unsaved_changes",
                    "message": "Houdini session has unsaved HIP changes.",
                    "detail": f"path={hip_path}",
                },
            )
            return

        _write_result(
            output_path,
            {
                "ok": True,
                "status": "stopping",
                "path": hip_path,
            },
        )
        hou.exit(0, suppress_save_prompt=True)
    except SystemExit:
        raise
    except hou.SystemExit:
        raise
    except BaseException as exc:
        _write_result(
            output_path,
            {
                "ok": False,
                "code": "session_stop_failed",
                "message": str(exc) or type(exc).__name__,
                "detail": traceback.format_exc(),
            },
        )
