from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Mapping
from uuid import uuid4

from houbridge.errors import BridgeError


@dataclass(frozen=True, slots=True)
class SessionRecord:
    session: int
    port: int
    pid: int
    process_start_identity: str | None = None

    def __post_init__(self) -> None:
        _positive_int(self.session, "session")
        if isinstance(self.port, bool) or not isinstance(self.port, int) or not 1 <= self.port <= 65535:
            raise ValueError("port must be an integer in the range 1..65535")
        _positive_int(self.pid, "pid")
        if self.process_start_identity is not None:
            if not isinstance(self.process_start_identity, str):
                raise TypeError("process_start_identity must be a string or None")
            normalized = self.process_start_identity.strip()
            if not normalized:
                raise ValueError("process_start_identity must not be empty")
            object.__setattr__(self, "process_start_identity", normalized)


@dataclass(frozen=True, slots=True)
class SessionRegistryState:
    primary: int | None
    sessions: Mapping[int, SessionRecord]

    def __post_init__(self) -> None:
        sessions = dict(self.sessions)
        for number, record in sessions.items():
            _positive_int(number, "session")
            if record.session != number:
                raise ValueError("session mapping key must match record.session")
        if self.primary is not None:
            _positive_int(self.primary, "primary")
            if self.primary not in sessions:
                raise ValueError("primary must reference a registered session")
        object.__setattr__(self, "sessions", MappingProxyType(sessions))

    @classmethod
    def empty(cls) -> "SessionRegistryState":
        return cls(primary=None, sessions={})


class SessionRegistry:
    """Global ``sessions.json`` owner."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> SessionRegistryState:
        if not self.path.exists():
            return SessionRegistryState.empty()
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise BridgeError(
                "session_registry_invalid",
                f"Unable to read Session registry: {self.path}",
                f"{type(exc).__name__}: {exc}",
            ) from exc
        return _parse_state(raw, self.path)

    def save(self, state: SessionRegistryState) -> None:
        payload = _encode_state(state)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        staging = self.path.parent / f".{self.path.name}.{uuid4().hex}.tmp"
        try:
            with staging.open("x", encoding="utf-8", newline="\n") as stream:
                json.dump(payload, stream, ensure_ascii=False, separators=(",", ":"))
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(staging, self.path)
        except OSError as exc:
            raise BridgeError(
                "session_registry_write_failed",
                f"Unable to write Session registry: {self.path}",
                f"{type(exc).__name__}: {exc}",
            ) from exc
        finally:
            try:
                staging.unlink()
            except FileNotFoundError:
                pass


def _parse_state(raw: object, path: Path) -> SessionRegistryState:
    if not isinstance(raw, dict) or set(raw) != {"primary", "sessions"}:
        raise _invalid_registry(path, "root must contain exactly primary and sessions")

    primary = raw["primary"]
    if primary is not None and (isinstance(primary, bool) or not isinstance(primary, int) or primary <= 0):
        raise _invalid_registry(path, "primary must be null or a positive integer")

    sessions_raw = raw["sessions"]
    if not isinstance(sessions_raw, dict):
        raise _invalid_registry(path, "sessions must be an object")

    sessions: dict[int, SessionRecord] = {}
    for key, record_raw in sessions_raw.items():
        if not isinstance(key, str) or not key.isascii() or not key.isdigit() or key.startswith("0"):
            raise _invalid_registry(path, "session keys must be canonical positive integers")
        session_number = int(key)
        if session_number <= 0:
            raise _invalid_registry(path, "session keys must be positive")
        if not isinstance(record_raw, dict):
            raise _invalid_registry(path, f"session {session_number} must be an object")
        allowed = {"port", "pid", "process_start_identity"}
        if not {"port", "pid"}.issubset(record_raw) or not set(record_raw).issubset(allowed):
            raise _invalid_registry(
                path,
                f"session {session_number} must contain port and pid only plus optional internal process_start_identity",
            )
        port = record_raw["port"]
        pid = record_raw["pid"]
        identity = record_raw.get("process_start_identity")
        try:
            sessions[session_number] = SessionRecord(
                session=session_number,
                port=port,  # type: ignore[arg-type]
                pid=pid,  # type: ignore[arg-type]
                process_start_identity=identity,  # type: ignore[arg-type]
            )
        except (TypeError, ValueError) as exc:
            raise _invalid_registry(path, f"session {session_number}: {exc}") from exc

    try:
        return SessionRegistryState(primary=primary, sessions=sessions)
    except ValueError as exc:
        raise _invalid_registry(path, str(exc)) from exc


def _encode_state(state: SessionRegistryState) -> dict[str, object]:
    sessions: dict[str, object] = {}
    for number in sorted(state.sessions):
        record = state.sessions[number]
        encoded: dict[str, object] = {"port": record.port, "pid": record.pid}
        if record.process_start_identity is not None:
            encoded["process_start_identity"] = record.process_start_identity
        sessions[str(number)] = encoded
    return {"primary": state.primary, "sessions": sessions}


def _invalid_registry(path: Path, detail: str) -> BridgeError:
    return BridgeError(
        "session_registry_invalid",
        f"Session registry is invalid: {path}",
        detail,
    )


def _positive_int(value: object, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{label} must be a positive integer")
