from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class HistorySessionPaths:
    """Paths owned by one exact Houdini process-incarnation History."""

    session_directory: Path

    @property
    def database(self) -> Path:
        return self.session_directory / "history.db"


@dataclass(frozen=True, slots=True)
class GlobalDataPaths:
    """User-level operational paths shared by all working directories."""

    data_dir: Path

    @classmethod
    def from_data_dir(cls, data_dir: Path) -> "GlobalDataPaths":
        return cls(data_dir=data_dir.expanduser())

    @property
    def sessions_registry(self) -> Path:
        return self.data_dir / "sessions.json"

    @property
    def tasks_database(self) -> Path:
        return self.data_dir / "tasks.db"

    @property
    def resources_database(self) -> Path:
        return self.data_dir / "resources.db"

    @property
    def history_directory(self) -> Path:
        return self.data_dir / "history"

    @property
    def capture_native_directory(self) -> Path:
        return self.data_dir / "capture-native"

    def history_session(self, session_key: str) -> HistorySessionPaths:
        # Session owns process-incarnation identity and its key representation.
        # Path ownership only places that opaque key below the global History root.
        return HistorySessionPaths(self.history_directory / session_key)


@dataclass(frozen=True, slots=True)
class WorkspaceSearchPaths:
    """Workspace-local authoritative scripts and rebuildable search state."""

    workspace_directory: Path

    @classmethod
    def for_cwd(cls, cwd: Path | None = None) -> "WorkspaceSearchPaths":
        workspace_directory = (cwd or Path.cwd()).resolve() / ".houbridge"
        return cls(workspace_directory=workspace_directory)

    @property
    def python_directory(self) -> Path:
        return self.workspace_directory / "python"

    @property
    def search_database(self) -> Path:
        return self.workspace_directory / "search.db"
