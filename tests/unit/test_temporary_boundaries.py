from __future__ import annotations

import os
from pathlib import Path

import pytest

from houbridge.temporary_artifact import TemporaryArtifactService
from houbridge.temporary_workspace import TemporaryWorkspaceService


def test_workspace_and_artifact_use_distinct_managed_directories(tmp_path: Path) -> None:
    workspaces = TemporaryWorkspaceService(temp_root=tmp_path)
    artifacts = TemporaryArtifactService(temp_root=tmp_path)

    workspace = workspaces.allocate()
    artifact = artifacts.publish_bytes(
        b"payload",
        namespace="resource",
        stem="dump",
        extension=".bin",
    )

    assert workspace.directory.parent == tmp_path / "houbridge" / "workspaces"
    assert artifact.parent == tmp_path / "houbridge" / "artifacts" / "resource"
    assert artifact not in workspace.directory.parents
    assert workspace.directory not in artifact.parents


def test_workspace_allocation_is_collision_safe(tmp_path: Path) -> None:
    service = TemporaryWorkspaceService(temp_root=tmp_path)

    first = service.allocate(prefix="exec")
    second = service.allocate(prefix="exec")

    assert first.directory != second.directory
    assert first.directory.is_dir()
    assert second.directory.is_dir()


def test_marker_publication_is_atomic_replace(tmp_path: Path) -> None:
    workspace = TemporaryWorkspaceService(temp_root=tmp_path).allocate()

    marker = workspace.publish_marker("started", b"first")
    workspace.publish_marker("started", b"second")

    assert marker.read_bytes() == b"second"
    assert not list(workspace.directory.glob(".*.tmp"))


def test_workspace_removal_is_explicit_not_age_based(tmp_path: Path) -> None:
    workspace = TemporaryWorkspaceService(temp_root=tmp_path).allocate()
    workspace.path_for("stdout").write_bytes(b"running")

    assert workspace.directory.exists()
    workspace.remove()
    assert not workspace.directory.exists()


def test_artifact_publication_preserves_exact_bytes(tmp_path: Path) -> None:
    service = TemporaryArtifactService(temp_root=tmp_path)
    payload = b"\x00\xffexact\r\nbytes"

    path = service.publish_bytes(
        payload,
        namespace="capture",
        stem="viewport",
        extension=".png",
    )

    assert path.read_bytes() == payload
    assert path.suffix == ".png"


def test_artifact_completed_source_file_is_copied_byte_for_byte(tmp_path: Path) -> None:
    service = TemporaryArtifactService(temp_root=tmp_path / "temp")
    source = tmp_path / "source.dat"
    source.write_bytes(b"source-bytes")

    published = service.publish_file(
        source,
        namespace="resource",
        stem="resource",
        extension=".bin",
    )

    assert published.read_bytes() == source.read_bytes()
    assert source.exists()


def test_same_artifact_stem_never_implicitly_overwrites(tmp_path: Path) -> None:
    service = TemporaryArtifactService(temp_root=tmp_path)

    first = service.publish_bytes(
        b"one",
        namespace="capture",
        stem="viewport",
        extension=".png",
    )
    second = service.publish_bytes(
        b"two",
        namespace="capture",
        stem="viewport",
        extension=".png",
    )

    assert first != second
    assert first.read_bytes() == b"one"
    assert second.read_bytes() == b"two"


def test_failed_artifact_staging_never_leaves_final_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = TemporaryArtifactService(temp_root=tmp_path)
    source = tmp_path / "source.bin"
    source.write_bytes(b"payload")

    def fail_copy(*args: object, **kwargs: object) -> None:
        raise OSError("copy failed")

    monkeypatch.setattr("houbridge._temporary_fs.shutil.copyfileobj", fail_copy)

    with pytest.raises(OSError, match="copy failed"):
        service.publish_file(
            source,
            namespace="resource",
            stem="dump",
            extension=".bin",
        )

    namespace = service.root / "resource"
    assert list(namespace.iterdir()) == []


def test_cleanup_uses_caller_cutoff_and_never_leaves_managed_namespace(
    tmp_path: Path,
) -> None:
    service = TemporaryArtifactService(temp_root=tmp_path)
    old = service.publish_bytes(
        b"old",
        namespace="capture",
        stem="old",
        extension=".png",
    )
    current = service.publish_bytes(
        b"new",
        namespace="capture",
        stem="new",
        extension=".png",
    )
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"outside")

    os.utime(old, (100.0, 100.0))
    os.utime(current, (300.0, 300.0))
    os.utime(outside, (100.0, 100.0))

    assert service.cleanup_before(namespace="capture", cutoff_timestamp=200.0) == 1
    assert not old.exists()
    assert current.exists()
    assert outside.exists()


def test_temporary_artifact_does_not_classify_format(tmp_path: Path) -> None:
    service = TemporaryArtifactService(temp_root=tmp_path)

    path = service.publish_bytes(
        b"not actually a png",
        namespace="resource",
        stem="caller-decided",
        extension=".png",
    )

    assert path.suffix == ".png"
    assert path.read_bytes() == b"not actually a png"
