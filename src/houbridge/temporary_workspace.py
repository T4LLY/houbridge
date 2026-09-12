from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from ._temporary_fs import atomic_write_bytes, managed_temporary_root, require_component


@dataclass(frozen=True, slots=True)
class TemporaryWorkspace:
    """Private invocation-local transport/recovery state."""

    directory: Path

    def path_for(self, name: str) -> Path:
        return self.directory / require_component(name, label="workspace filename")

    def publish_marker(self, name: str, payload: bytes = b"") -> Path:
        marker = self.path_for(name)
        atomic_write_bytes(marker, payload)
        return marker

    def remove(self) -> None:
        shutil.rmtree(self.directory, ignore_errors=True)


class TemporaryWorkspaceService:
    """Allocate isolated private invocation workspaces below the OS temp root."""

    def __init__(self, *, temp_root: Path | None = None) -> None:
        self._root = managed_temporary_root(temp_root, "workspaces")

    @property
    def root(self) -> Path:
        return self._root

    def allocate(self, *, prefix: str = "invocation") -> TemporaryWorkspace:
        prefix = require_component(prefix, label="workspace prefix")
        directory = Path(tempfile.mkdtemp(prefix=f"{prefix}-", dir=self._root))
        return TemporaryWorkspace(directory)
