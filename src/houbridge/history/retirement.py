from __future__ import annotations

import shutil

from houbridge.paths import GlobalDataPaths
from houbridge.process_coordination import (
    InterprocessFileLock,
    InterprocessFileLockTimeout,
    ProcessIdentity,
)

from .identity import history_session_key
from .locking import history_database_lock_path


class HistoryRetirementService:
    """Delete stale History owned by a no-longer-current process incarnation."""

    def __init__(
        self,
        paths: GlobalDataPaths,
        *,
        lock_timeout_seconds: float = 120.0,
    ) -> None:
        self._paths = paths
        self._lock_timeout_seconds = float(lock_timeout_seconds)
        self._file_lock = InterprocessFileLock()

    def retire(self, identity: ProcessIdentity) -> bool:
        session_paths = self._paths.history_session(history_session_key(identity))
        session_dir = session_paths.session_directory
        if not session_dir.exists():
            return False
        try:
            with self._file_lock.acquire(
                history_database_lock_path(session_paths.database),
                timeout_seconds=self._lock_timeout_seconds,
            ):
                if not session_dir.exists():
                    return False
                shutil.rmtree(session_dir)
        except (InterprocessFileLockTimeout, OSError):
            # Stale History retirement is explicitly best-effort. A locked or
            # temporarily inaccessible directory must not invalidate Session state.
            return False
        return True
