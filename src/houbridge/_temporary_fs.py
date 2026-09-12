from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from uuid import uuid4


def managed_temporary_root(temp_root: Path | None, boundary: str) -> Path:
    root = (temp_root or Path(tempfile.gettempdir())).resolve()
    managed = root / "houbridge" / boundary
    managed.mkdir(parents=True, exist_ok=True)
    return managed


def require_component(value: str, *, label: str) -> str:
    if not value or value in {".", ".."}:
        raise ValueError(f"{label} must be a non-empty path component")
    if Path(value).name != value or "/" in value or "\\" in value:
        raise ValueError(f"{label} must be one path component")
    return value


def atomic_write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    staging = path.parent / f".{path.name}.{uuid4().hex}.tmp"
    try:
        with staging.open("xb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(staging, path)
    finally:
        try:
            staging.unlink()
        except FileNotFoundError:
            pass


def stage_bytes(directory: Path, payload: bytes) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    staging = directory / f".publish-{uuid4().hex}.tmp"
    try:
        with staging.open("xb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        try:
            staging.unlink()
        except FileNotFoundError:
            pass
        raise
    return staging


def stage_file(directory: Path, source: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    staging = directory / f".publish-{uuid4().hex}.tmp"
    try:
        with source.open("rb") as input_stream, staging.open("xb") as output_stream:
            shutil.copyfileobj(input_stream, output_stream)
            output_stream.flush()
            os.fsync(output_stream.fileno())
    except BaseException:
        try:
            staging.unlink()
        except FileNotFoundError:
            pass
        raise
    return staging
