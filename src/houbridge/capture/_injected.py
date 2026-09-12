from __future__ import annotations

import json
from pathlib import Path

from houbridge.temporary_workspace import TemporaryWorkspace


def write_runpy_runner(
    workspace: TemporaryWorkspace,
    *,
    script_path: Path,
    request_path: Path,
    filename: str,
) -> Path:
    runner = workspace.path_for(filename)
    runner.write_text(
        "from __future__ import annotations\n"
        "import runpy\n"
        f"_runtime = runpy.run_path({json.dumps(str(script_path.resolve()), ensure_ascii=False)})\n"
        f"_runtime['run']({json.dumps(str(request_path), ensure_ascii=False)})\n",
        encoding="utf-8",
        newline="\n",
    )
    return runner
