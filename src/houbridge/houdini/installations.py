from __future__ import annotations

import os
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from houbridge.errors import BridgeError


_VERSION_RE = re.compile(r"(?:Houdini\s*)?(\d+)\.(\d+)(?:\.(\d+))?", re.IGNORECASE)


@dataclass(frozen=True)
class HoudiniInstallation:
    root: Path
    bin_dir: Path
    houdini: Path
    hcommand: Path
    version: tuple[int, int, int]


def discover_houdini_installations(
    *,
    environ: Mapping[str, str] | None = None,
    platform: str | None = None,
) -> tuple[HoudiniInstallation, ...]:
    """Discover complete local Houdini installations without consulting Houbridge config."""
    env = os.environ if environ is None else environ
    platform_name = sys.platform if platform is None else platform
    roots: list[Path] = []

    hfs = env.get("HFS")
    if hfs:
        roots.append(Path(hfs))

    if platform_name.startswith("win"):
        program_files = env.get("ProgramFiles")
        if program_files is None and environ is None:
            program_files = r"C:\Program Files"
        if program_files:
            sidefx_root = Path(program_files) / "Side Effects Software"
            if sidefx_root.is_dir():
                roots.extend(sidefx_root.glob("Houdini*"))
    elif platform_name.startswith("linux"):
        roots.extend(Path("/opt").glob("hfs*"))

    search_path = env.get("PATH") if environ is None else env.get("PATH", "")
    path_hcommand = shutil.which(_executable_name("hcommand", platform_name), path=search_path)
    if path_hcommand:
        roots.append(Path(path_hcommand).resolve().parent.parent)

    path_houdini = shutil.which(_executable_name("houdini", platform_name), path=search_path)
    if path_houdini:
        candidate = Path(path_houdini).resolve()
        if (candidate.parent / _executable_name("hcommand", platform_name)).is_file():
            roots.append(candidate.parent.parent)

    unique: dict[Path, HoudiniInstallation] = {}
    for root in roots:
        installation = _installation_from_root(root, platform_name)
        if installation is not None:
            unique[installation.root] = installation

    return tuple(
        sorted(
            unique.values(),
            key=lambda item: (item.version, str(item.root).casefold()),
            reverse=True,
        )
    )


def resolve_transport_hcommand(
    *,
    installation: HoudiniInstallation | None = None,
    environ: Mapping[str, str] | None = None,
    platform: str | None = None,
) -> Path:
    """Resolve SideFX hcommand used for openport transport.

    This deliberately does not read ``[houdini].hcommand``. That setting selects the
    Session launch executable; transport tooling is resolved from the selected
    installation, a usable HFS, PATH, or standard installation discovery.
    """
    env = os.environ if environ is None else environ
    platform_name = sys.platform if platform is None else platform
    executable_name = _executable_name("hcommand", platform_name)

    if installation is not None and installation.hcommand.is_file():
        return installation.hcommand.resolve()

    hfs = env.get("HFS")
    if hfs:
        candidate = Path(hfs).expanduser() / "bin" / executable_name
        if candidate.is_file():
            return candidate.resolve()

    search_path = env.get("PATH") if environ is None else env.get("PATH", "")
    discovered = shutil.which(executable_name, path=search_path)
    if discovered:
        return Path(discovered).resolve()

    installations = discover_houdini_installations(environ=env, platform=platform_name)
    if installations:
        return installations[0].hcommand.resolve()

    raise BridgeError(
        "hcommand_not_found",
        "Unable to locate SideFX hcommand for Houdini transport.",
    )


def subprocess_environment_for(
    executable: str | Path,
    *,
    environ: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Build an environment consistent with an executable inside a Houdini bin dir."""
    env = dict(os.environ if environ is None else environ)
    path = Path(executable).expanduser()
    if not path.is_absolute() or path.parent.name.casefold() != "bin":
        return env

    bin_dir = path.parent.resolve()
    root = bin_dir.parent
    env["HFS"] = str(root)

    current_path = env.get("PATH", "")
    parts = [part for part in current_path.split(os.pathsep) if part]
    normalized_bin = os.path.normcase(str(bin_dir))
    if normalized_bin not in {os.path.normcase(part) for part in parts}:
        env["PATH"] = str(bin_dir) + (os.pathsep + current_path if current_path else "")
    return env


def _installation_from_root(
    root: Path,
    platform_name: str,
) -> HoudiniInstallation | None:
    try:
        resolved = root.expanduser().resolve()
    except OSError:
        return None
    if not resolved.is_dir():
        return None

    bin_dir = resolved / "bin"
    hcommand = bin_dir / _executable_name("hcommand", platform_name)
    houdini = bin_dir / _executable_name("houdini", platform_name)
    if not hcommand.is_file() or not houdini.is_file():
        return None

    return HoudiniInstallation(
        root=resolved,
        bin_dir=bin_dir,
        houdini=houdini,
        hcommand=hcommand,
        version=_version_from_path(resolved),
    )


def _executable_name(stem: str, platform_name: str) -> str:
    return f"{stem}.exe" if platform_name.startswith("win") else stem


def _version_from_path(path: Path) -> tuple[int, int, int]:
    for value in (path.name, str(path)):
        match = _VERSION_RE.search(value)
        if match:
            major, minor, build = match.groups()
            return int(major), int(minor), int(build or 0)
    return 0, 0, 0
