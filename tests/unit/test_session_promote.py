from __future__ import annotations

from pathlib import Path

import pytest

from houbridge.errors import BridgeError
from houbridge.process_coordination import ProcessIdentity
from houbridge.session.probe import SessionProbeResult
from houbridge.session.promote import SessionPromoteService
from houbridge.session.registry import SessionRecord, SessionRegistry, SessionRegistryState
from houbridge.session.resolver import SessionResolver
from houbridge.session.stale import SessionStaleCleanupService


class FakeProbe:
    def __init__(self, results: dict[int, SessionProbeResult | BridgeError]) -> None:
        self.results = results
        self.calls: list[int] = []

    def inspect(self, port: int) -> SessionProbeResult:
        self.calls.append(port)
        result = self.results[port]
        if isinstance(result, BridgeError):
            raise result
        return result


def _probe_result(*, pid: int, port: int) -> SessionProbeResult:
    return SessionProbeResult(
        pid=pid,
        version="22.0.429",
        license="Commercial",
        file=None,
        headless=False,
        open_ports=(port,),
    )


def _identity_reader(values: dict[int, str]):
    def read(pid: int) -> ProcessIdentity:
        value = values.get(pid)
        if value is None:
            raise ProcessLookupError(pid)
        return ProcessIdentity(pid, value)

    return read


def _promote_service(
    registry: SessionRegistry,
    probe: FakeProbe,
    identities: dict[int, str],
) -> SessionPromoteService:
    identity_reader = _identity_reader(identities)
    resolver = SessionResolver(
        registry,
        probe,  # type: ignore[arg-type]
        identity_reader=identity_reader,
    )
    cleanup = SessionStaleCleanupService(
        registry,
        identity_reader=identity_reader,
    )
    return SessionPromoteService(registry, resolver, stale_cleanup=cleanup)


def test_promote_replaces_primary_without_renumbering_sessions(tmp_path: Path) -> None:
    registry = SessionRegistry(tmp_path / "sessions.json")
    registry.save(
        SessionRegistryState(
            primary=1,
            sessions={
                1: SessionRecord(1, 49152, 1001, "start-1"),
                3: SessionRecord(3, 49154, 1003, "start-3"),
            },
        )
    )
    probe = FakeProbe({49154: _probe_result(pid=1003, port=49154)})
    service = _promote_service(
        registry,
        probe,
        {1001: "start-1", 1003: "start-3"},
    )

    assert service.promote(3) == {"primary": 3}

    state = registry.load()
    assert state.primary == 3
    assert set(state.sessions) == {1, 3}
    assert state.sessions[1].pid == 1001
    assert state.sessions[3].pid == 1003


def test_promote_missing_session_keeps_previous_primary(tmp_path: Path) -> None:
    registry = SessionRegistry(tmp_path / "sessions.json")
    registry.save(
        SessionRegistryState(
            primary=1,
            sessions={1: SessionRecord(1, 49152, 1001, "start-1")},
        )
    )
    probe = FakeProbe({})
    service = _promote_service(registry, probe, {1001: "start-1"})

    with pytest.raises(BridgeError) as caught:
        service.promote(3)

    assert caught.value.code == "session_not_found"
    assert registry.load().primary == 1
    assert probe.calls == []


def test_promote_unreachable_live_pid_keeps_previous_primary(tmp_path: Path) -> None:
    registry = SessionRegistry(tmp_path / "sessions.json")
    registry.save(
        SessionRegistryState(
            primary=1,
            sessions={
                1: SessionRecord(1, 49152, 1001, "start-1"),
                3: SessionRecord(3, 49154, 1003, "start-3"),
            },
        )
    )
    probe = FakeProbe(
        {
            49154: BridgeError(
                "houdini_transport_failed",
                "Unable to contact registered Houdini session.",
            )
        }
    )
    service = _promote_service(
        registry,
        probe,
        {1001: "start-1", 1003: "start-3"},
    )

    with pytest.raises(BridgeError) as caught:
        service.promote(3)

    assert caught.value.code == "houdini_transport_failed"
    assert registry.load().primary == 1


def test_promote_cleans_dead_primary_before_selecting_live_target(tmp_path: Path) -> None:
    registry = SessionRegistry(tmp_path / "sessions.json")
    registry.save(
        SessionRegistryState(
            primary=2,
            sessions={
                2: SessionRecord(2, 49153, 1002, "dead-start"),
                3: SessionRecord(3, 49154, 1003, "start-3"),
            },
        )
    )
    probe = FakeProbe({49154: _probe_result(pid=1003, port=49154)})
    service = _promote_service(registry, probe, {1003: "start-3"})

    assert service.promote(3) == {"primary": 3}

    state = registry.load()
    assert state.primary == 3
    assert set(state.sessions) == {3}


def test_stale_cleanup_removes_reused_pid_and_unsets_primary(tmp_path: Path) -> None:
    registry = SessionRegistry(tmp_path / "sessions.json")
    registry.save(
        SessionRegistryState(
            primary=2,
            sessions={
                1: SessionRecord(1, 49152, 1001, "start-1"),
                2: SessionRecord(2, 49153, 1002, "old-start"),
            },
        )
    )
    cleanup = SessionStaleCleanupService(
        registry,
        identity_reader=_identity_reader({1001: "start-1", 1002: "new-start"}),
    )

    state = cleanup.cleanup()

    assert state.primary is None
    assert set(state.sessions) == {1}
    assert registry.load().primary is None
    assert set(registry.load().sessions) == {1}


@pytest.mark.parametrize(
    "identity_error",
    [PermissionError("access denied"), OSError("identity read failed")],
    ids=["permission-error", "os-error"],
)
def test_stale_cleanup_preserves_session_when_identity_read_is_inconclusive(
    tmp_path: Path,
    identity_error: OSError,
) -> None:
    registry = SessionRegistry(tmp_path / "sessions.json")
    record = SessionRecord(1, 49152, 1001, "start-1")
    registry.save(SessionRegistryState(primary=1, sessions={1: record}))
    retired: list[SessionRecord] = []

    def unreadable_identity(_pid: int) -> ProcessIdentity:
        raise identity_error

    cleanup = SessionStaleCleanupService(
        registry,
        identity_reader=unreadable_identity,
        on_stale=retired.append,
    )

    state = cleanup.cleanup()

    assert state.primary == 1
    assert state.sessions == {1: record}
    assert registry.load() == state
    assert retired == []


def test_promote_preserves_registry_changes_made_during_target_probe(tmp_path: Path) -> None:
    path = tmp_path / "sessions.json"
    registry = SessionRegistry(path)
    registry.save(
        SessionRegistryState(
            primary=1,
            sessions={
                1: SessionRecord(1, 49152, 1001, "start-1"),
                3: SessionRecord(3, 49154, 1003, "start-3"),
            },
        )
    )

    concurrent_registry = SessionRegistry(path)

    class ResolverWithConcurrentRegistration:
        def resolve_record(self, record: SessionRecord) -> object:
            with concurrent_registry.locked():
                current = concurrent_registry.load()
                sessions = dict(current.sessions)
                sessions[2] = SessionRecord(2, 49153, 1002, "start-2")
                concurrent_registry.save(
                    SessionRegistryState(primary=current.primary, sessions=sessions)
                )
            return object()

    cleanup = SessionStaleCleanupService(
        registry,
        identity_reader=_identity_reader({1001: "start-1", 1003: "start-3"}),
    )
    service = SessionPromoteService(
        registry,
        ResolverWithConcurrentRegistration(),  # type: ignore[arg-type]
        stale_cleanup=cleanup,
    )

    assert service.promote(3) == {"primary": 3}

    state = registry.load()
    assert state.primary == 3
    assert set(state.sessions) == {1, 2, 3}
    assert state.sessions[2].pid == 1002
