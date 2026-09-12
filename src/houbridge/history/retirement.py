from __future__ import annotations

import shutil

from houbridge.paths import GlobalDataPaths
from houbridge.process_coordination import ProcessIdentity

from .identity import history_session_key


class HistoryRetirementService:
    """Delete stale History owned by a no-longer-current process incarnation."""

    def __init__(self, paths: GlobalDataPaths) -> None:
        self._paths = paths

    def retire(self, identity: ProcessIdentity) -> bool:
        session_dir = self._paths.history_session(history_session_key(identity)).session_directory
        if not session_dir.exists():
            return False
        shutil.rmtree(session_dir)
        return True
