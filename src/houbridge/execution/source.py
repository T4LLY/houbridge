from __future__ import annotations

import tokenize
from pathlib import Path
from typing import Iterable

from houbridge.errors import BridgeError

from .models import ExecutionInvocation, normalized_origin_cwd


def prepare_file_invocation(
    source_path: Path,
    *,
    args: Iterable[str] = (),
    purpose: str | None = None,
    origin_cwd: Path | None = None,
) -> ExecutionInvocation:
    """Read one caller file with Python's source-encoding rules."""

    supplied_path = str(source_path)
    try:
        with tokenize.open(source_path) as stream:
            source = stream.read()
    except (OSError, UnicodeError, SyntaxError, LookupError) as exc:
        raise BridgeError(
            "python_file_read_failed",
            f"Unable to read Python file: {source_path}",
            f"{type(exc).__name__}: {exc}",
        ) from exc

    validate_python_source(source)
    argv = (supplied_path, *(str(value) for value in args))
    return ExecutionInvocation(
        source=source,
        source_path=supplied_path,
        argv=argv,
        purpose=purpose,
        origin_cwd=normalized_origin_cwd(origin_cwd),
    )


def validate_python_source(source: str) -> None:
    if "\x00" in source:
        raise BridgeError(
            "invalid_python_source",
            "Python source contains a NUL character.",
        )
