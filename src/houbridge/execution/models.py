from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


ResultKind = Literal["json", "text"]


@dataclass(frozen=True, slots=True)
class ExecutionInvocation:
    """Caller-side source and metadata for one managed Python invocation."""

    source: str
    source_path: str | None
    argv: tuple[str, ...]
    purpose: str | None
    origin_cwd: str

    @property
    def source_sha256(self) -> str:
        return hashlib.sha256(self.source.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class DeclaredResult:
    kind: ResultKind
    payload: bytes

    @property
    def mime(self) -> str:
        return "application/json" if self.kind == "json" else "text/plain"

    def inline_value(self) -> object:
        text = self.payload.decode("utf-8", errors="strict")
        if self.kind == "json":
            return json.loads(text, parse_constant=_reject_non_finite_json_constant)
        return text


@dataclass(frozen=True, slots=True)
class ExecutionOutcome:
    python_ok: bool
    result: DeclaredResult | None
    stdout: str
    stderr: str
    traceback: str | None


def normalized_origin_cwd(path: Path | None = None) -> str:
    return str((Path.cwd() if path is None else path).resolve())


def _reject_non_finite_json_constant(_value: str) -> None:
    raise ValueError("Non-finite numbers are not valid JSON.")
