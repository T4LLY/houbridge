from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from typing import Any

from houbridge.formatting import CanonicalJsonNumber


def serialize_public_json(value: Any) -> str:
    """Serialize public CLI JSON with the canonical numeric contract."""

    if isinstance(value, CanonicalJsonNumber):
        return value.token
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("Public JSON does not support non-finite numbers.")
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        )
    if isinstance(value, Mapping):
        parts: list[str] = []
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("Public JSON object keys must be strings.")
            encoded_key = json.dumps(key, ensure_ascii=False)
            parts.append(f"{encoded_key}:{serialize_public_json(item)}")
        return "{" + ",".join(parts) + "}"
    if isinstance(value, Sequence) and not isinstance(
        value,
        (str, bytes, bytearray),
    ):
        return "[" + ",".join(serialize_public_json(item) for item in value) + "]"
    raise TypeError(f"Unsupported public JSON value: {type(value).__name__}")


def public_json_size(value: Any) -> int:
    return len(serialize_public_json(value).encode("utf-8"))
