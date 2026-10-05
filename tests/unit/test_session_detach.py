from __future__ import annotations

from pathlib import Path

import pytest

from houbridge.errors import BridgeError
from houbridge.session.detach import SessionDetachService
from houbridge.session.registry import SessionRecord, SessionRegistry, SessionRegistryState


def _registry(tmp_path: Path) -> SessionRegistry:
    return SessionRegistry(tmp_path / "sessions.json")


def test_detach_removes_only_requested_non_primary_session(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    registry.save(
        SessionRegistryState(
            primary=1,
            sessions={
                1: SessionRecord(1, 49151, 1001, "process-1"),
                3: SessionRecord(3, 49153, 1003, "process-3"),
            },
        )
    )

    result = SessionDetachService(registry).detach(3)

    assert result == {"detached": 3}
    state = registry.load()
    assert state.primary == 1
    assert set(state.sessions) == {1}


def test_detach_primary_unsets_primary_without_promoting_another_session(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    registry.save(
        SessionRegistryState(
            primary=1,
            sessions={
                1: SessionRecord(1, 49151, 1001, "process-1"),
                3: SessionRecord(3, 49153, 1003, "process-3"),
            },
        )
    )

    result = SessionDetachService(registry).detach(1)

    assert result == {"detached": 1}
    state = registry.load()
    assert state.primary is None
    assert set(state.sessions) == {3}


def test_detach_missing_session_does_not_change_registry(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    original = SessionRegistryState(
        primary=1,
        sessions={1: SessionRecord(1, 49151, 1001, "process-1")},
    )
    registry.save(original)

    with pytest.raises(BridgeError) as exc_info:
        SessionDetachService(registry).detach(3)

    assert exc_info.value.code == "session_not_found"
    assert registry.load() == original


def test_detach_rejects_non_positive_session_without_mutation(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    original = SessionRegistryState(
        primary=1,
        sessions={1: SessionRecord(1, 49151, 1001, "process-1")},
    )
    registry.save(original)

    with pytest.raises(BridgeError) as exc_info:
        SessionDetachService(registry).detach(0)

    assert exc_info.value.code == "invalid_session"
    assert registry.load() == original
