from __future__ import annotations

import json
from pathlib import Path

from houbridge.temporary_workspace import TemporaryWorkspace

from .workspace import StagedTaskInvocation


class TaskScriptBuilder:
    """Stage a tiny invocation shim around the physical Houdini-side Task runtime."""

    def __init__(self, runtime_script: Path | None = None) -> None:
        if runtime_script is None:
            from houbridge.houdini.scripts.task import runtime

            runtime_script = Path(runtime.__file__)
        self._runtime_script = runtime_script.resolve()

    def stage(self, workspace: TemporaryWorkspace, request_path: Path) -> StagedTaskInvocation:
        script_path = workspace.path_for("run.py")
        script_path.write_text(
            "from __future__ import annotations\n"
            "import runpy\n"
            f"_runtime = runpy.run_path({json.dumps(str(self._runtime_script), ensure_ascii=False)})\n"
            f"_runtime['run']({json.dumps(str(request_path.resolve()), ensure_ascii=False)})\n",
            encoding="utf-8",
            newline="\n",
        )
        return StagedTaskInvocation(
            workspace=workspace,
            request_path=request_path,
            script_path=script_path,
        )
