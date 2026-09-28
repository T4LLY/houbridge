from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

from ._temporary_fs import managed_temporary_root, require_component, stage_bytes, stage_file


class TemporaryArtifactService:
    """Publish completed caller-visible files without classifying their format."""

    def __init__(self, *, temp_root: Path | None = None) -> None:
        self._root = managed_temporary_root(temp_root, "artifacts")

    @property
    def root(self) -> Path:
        return self._root

    def publish_bytes(
        self,
        payload: bytes,
        *,
        namespace: str,
        stem: str,
        extension: str,
    ) -> Path:
        directory = self._namespace_directory(namespace)
        staging = stage_bytes(directory, payload)
        return self._publish_staged(staging, directory, stem=stem, extension=extension)

    def publish_file(
        self,
        source: Path,
        *,
        namespace: str,
        stem: str,
        extension: str,
    ) -> Path:
        directory = self._namespace_directory(namespace)
        staging = stage_file(directory, source)
        return self._publish_staged(staging, directory, stem=stem, extension=extension)

    def publish_file_exact(
        self,
        source: Path,
        *,
        namespace: str,
        stem: str,
        extension: str,
    ) -> Path:
        """Publish one completed file under an exact caller-selected name.

        This keeps the Temporary Artifact boundary responsible for staging and
        atomic no-overwrite publication while allowing features such as Capture
        to own a readable sequential naming contract.
        """

        directory = self._namespace_directory(namespace)
        staging = stage_file(directory, source)
        return self._publish_staged_exact(
            staging,
            directory,
            stem=stem,
            extension=extension,
        )

    def cleanup_before(self, *, namespace: str, cutoff_timestamp: float) -> int:
        """Delete managed artifact files selected by a caller-owned retention cutoff."""

        directory = self._namespace_directory(namespace, create=False)
        if not directory.is_dir():
            return 0

        removed = 0
        for path in directory.iterdir():
            if not path.is_file():
                continue
            try:
                if path.stat().st_mtime <= cutoff_timestamp:
                    path.unlink()
                    removed += 1
            except FileNotFoundError:
                continue
        return removed

    def _namespace_directory(self, namespace: str, *, create: bool = True) -> Path:
        namespace = require_component(namespace, label="artifact namespace")
        directory = self._root / namespace
        if create:
            directory.mkdir(parents=True, exist_ok=True)
        return directory

    @staticmethod
    def _validate_name(stem: str, extension: str) -> tuple[str, str]:
        stem = require_component(stem, label="artifact stem")
        if extension:
            if not extension.startswith(".") or extension in {".", ".."}:
                raise ValueError("artifact extension must be empty or start with '.'")
            if "/" in extension or "\\" in extension:
                raise ValueError("artifact extension must not contain path separators")
        return stem, extension

    def _publish_staged_exact(
        self,
        staging: Path,
        directory: Path,
        *,
        stem: str,
        extension: str,
    ) -> Path:
        stem, extension = self._validate_name(stem, extension)
        final = directory / f"{stem}{extension}"
        try:
            os.link(staging, final)
            staging.unlink()
            return final
        finally:
            try:
                staging.unlink()
            except FileNotFoundError:
                pass

    def _publish_staged(
        self,
        staging: Path,
        directory: Path,
        *,
        stem: str,
        extension: str,
    ) -> Path:
        stem, extension = self._validate_name(stem, extension)
        try:
            while True:
                final = directory / f"{stem}-{uuid4().hex}{extension}"
                try:
                    # The staging file is complete and closed before linking it into the
                    # public namespace. A hard link gives us atomic no-overwrite
                    # publication on the same temporary filesystem.
                    os.link(staging, final)
                except FileExistsError:
                    continue
                staging.unlink()
                return final
        finally:
            try:
                staging.unlink()
            except FileNotFoundError:
                pass
