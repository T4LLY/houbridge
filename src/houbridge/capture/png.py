from __future__ import annotations

import struct
from pathlib import Path

from houbridge.errors import BridgeError


def png_size(path: Path) -> tuple[int, int]:
    try:
        with path.open("rb") as stream:
            header = stream.read(24)
    except OSError as exc:
        raise BridgeError(
            "invalid_png",
            "Screenshot output is not a readable PNG.",
            f"{type(exc).__name__}: {exc}",
        ) from exc
    if len(header) < 24 or header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
        raise BridgeError("invalid_png", "Screenshot output is not a valid PNG.")
    width, height = struct.unpack(">II", header[16:24])
    if width <= 0 or height <= 0:
        raise BridgeError("invalid_png", "Screenshot PNG dimensions are invalid.")
    return width, height
