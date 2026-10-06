from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal

import filetype  # type: ignore[import-untyped]


ContentClass = Literal["binary", "text", "json"]


@dataclass(frozen=True, slots=True)
class ContentClassification:
    content_class: ContentClass
    mime: str
    decoded_text: str | None


def classify_content(payload: bytes) -> ContentClassification:
    """Classify exact Resource payload bytes in the OpenSpec-defined order."""

    detected = filetype.guess(payload)
    if detected is not None:
        return ContentClassification(
            content_class="binary",
            mime=detected.mime,
            decoded_text=None,
        )

    try:
        text = payload.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        return ContentClassification(
            content_class="binary",
            mime="application/octet-stream",
            decoded_text=None,
        )

    if _contains_binary_control(text):
        return ContentClassification(
            content_class="binary",
            mime="application/octet-stream",
            decoded_text=None,
        )

    try:
        json.loads(text, parse_constant=_reject_non_finite_json_constant)
    except (json.JSONDecodeError, ValueError, RecursionError):
        return ContentClassification(
            content_class="text",
            mime="text/plain",
            decoded_text=text,
        )

    return ContentClassification(
        content_class="json",
        mime="application/json",
        decoded_text=text,
    )


def _reject_non_finite_json_constant(_value: str) -> None:
    raise ValueError("Non-finite numbers are not valid JSON.")


def _contains_binary_control(text: str) -> bool:
    for character in text:
        codepoint = ord(character)
        if codepoint == 0x7F:
            return True
        if codepoint < 0x20 and codepoint not in (0x09, 0x0A, 0x0D):
            return True
    return False
