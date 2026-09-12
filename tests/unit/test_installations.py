from __future__ import annotations

import os
from pathlib import Path

import pytest

from houbridge.errors import BridgeError
from houbridge.houdini.installations import (
    HoudiniInstallation,
    discover_houdini_installations,
    resolve_session_launch_executable,
    resolve_transport_hcommand,
    subprocess_environment_for,
)


def _make_installation(root: Path, *, platform: str = "win32") -> None:
    suffix = ".exe" if platform.startswith("win") else ""
    bin_dir = root / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / f"houdini{suffix}").write_bytes(b"")
    (bin_dir / f"hcommand{suffix}").write_bytes(b"")
    (bin_dir / f"hython{suffix}").write_bytes(b"")


def test_discovers_newest_standard_windows_installation(tmp_path: Path) -> None:
    program_files = tmp_path / "Program Files"
    old = program_files / "Side Effects Software" / "Houdini20.5.100"
    new = program_files / "Side Effects Software" / "Houdini21.0.777"
    _make_installation(old)
    _make_installation(new)

    found = discover_houdini_installations(
        environ={"ProgramFiles": str(program_files), "PATH": ""},
        platform="win32",
    )

    assert [item.version for item in found] == [(21, 0, 777), (20, 5, 100)]
    assert found[0].hcommand == (new / "bin" / "hcommand.exe").resolve()


def test_transport_hcommand_prefers_selected_installation(tmp_path: Path) -> None:
    selected_root = tmp_path / "Houdini21.0.1"
    hfs_root = tmp_path / "Houdini20.5.1"
    _make_installation(selected_root)
    _make_installation(hfs_root)

    selected = HoudiniInstallation(
        root=selected_root.resolve(),
        bin_dir=(selected_root / "bin").resolve(),
        houdini=(selected_root / "bin" / "houdini.exe").resolve(),
        hcommand=(selected_root / "bin" / "hcommand.exe").resolve(),
        version=(21, 0, 1),
    )

    resolved = resolve_transport_hcommand(
        installation=selected,
        environ={"HFS": str(hfs_root), "PATH": ""},
        platform="win32",
    )

    assert resolved == (selected_root / "bin" / "hcommand.exe").resolve()


def test_transport_hcommand_uses_usable_hfs(tmp_path: Path) -> None:
    root = tmp_path / "Houdini21.0.1"
    _make_installation(root)

    resolved = resolve_transport_hcommand(
        environ={"HFS": str(root), "PATH": ""},
        platform="win32",
    )

    assert resolved == (root / "bin" / "hcommand.exe").resolve()


def test_transport_hcommand_missing_is_structured_error() -> None:
    with pytest.raises(BridgeError) as caught:
        resolve_transport_hcommand(environ={"PATH": ""}, platform="win32")

    assert caught.value.code == "hcommand_not_found"


def test_subprocess_environment_matches_selected_bin(tmp_path: Path) -> None:
    root = tmp_path / "Houdini21.0.1"
    _make_installation(root)
    bin_dir = (root / "bin").resolve()

    env = subprocess_environment_for(
        bin_dir / "hcommand.exe",
        environ={"HFS": str(tmp_path / "other"), "PATH": "existing"},
    )

    assert env["HFS"] == str(root.resolve())
    assert env["PATH"].split(os.pathsep)[0] == str(bin_dir)


def test_session_launch_resolution_prefers_explicit_then_config_then_default(tmp_path: Path) -> None:
    explicit_root = tmp_path / "Houdini21.0.1"
    configured_root = tmp_path / "Houdini20.5.1"
    _make_installation(explicit_root)
    _make_installation(configured_root)

    explicit = explicit_root / "bin" / "houdini.exe"
    configured = configured_root / "bin" / "houdini.exe"

    assert resolve_session_launch_executable(
        explicit,
        str(configured),
        headless=False,
        environ={"PATH": ""},
        platform="win32",
    ) == explicit.resolve()
    assert resolve_session_launch_executable(
        None,
        str(configured),
        headless=False,
        environ={"PATH": ""},
        platform="win32",
    ) == configured.resolve()


def test_session_headless_resolution_uses_matching_hython(tmp_path: Path) -> None:
    root = tmp_path / "Houdini21.0.1"
    _make_installation(root)

    resolved = resolve_session_launch_executable(
        root / "bin" / "houdini.exe",
        None,
        headless=True,
        environ={"PATH": ""},
        platform="win32",
    )

    assert resolved == (root / "bin" / "hython.exe").resolve()


def test_session_launch_override_does_not_accept_argument_string(tmp_path: Path) -> None:
    root = tmp_path / "Houdini21.0.1"
    _make_installation(root)

    with pytest.raises(BridgeError) as caught:
        resolve_session_launch_executable(
            f'{root / "bin" / "houdini.exe"} -foreground',
            None,
            headless=False,
            environ={"PATH": ""},
            platform="win32",
        )

    assert caught.value.code == "houdini_executable_not_found"
