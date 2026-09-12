from __future__ import annotations

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import pytest

from houbridge.config import ensure_config_file, load_config
from houbridge.execution.models import ExecutionInvocation
from houbridge.houdini.transport import HoudiniTransport
from houbridge.process_coordination import ProcessIdentity
from houbridge.semantic_id import SemanticBase
from houbridge.session.probe import SessionProbeResult
from houbridge.session.registry import SessionRecord
from houbridge.session.resolver import ResolvedSession
from houbridge.task import FrozenDispatchContext, TaskStore, TaskSubmission, freeze_task_submission


class FixedSemanticGenerator:
    def __init__(self, prefix: str = "geometry-build-cache") -> None:
        self.prefix = prefix
        self.calls: list[tuple[str, str]] = []

    def generate(self, text: str, *, fallback_stem: str) -> SemanticBase:
        self.calls.append((text, fallback_stem))
        return SemanticBase(prefix=self.prefix, tags=tuple(self.prefix.split("-")))


def _dispatch(environment: dict[str, str] | None = None) -> FrozenDispatchContext:
    return FrozenDispatchContext(
        session=2,
        port=17345,
        pid=4242,
        process_start_identity="boot-4242",
        transport_executable="/opt/hfs/bin/hcommand",
        transport_timeout_seconds=12.5,
        transport_environment=environment or {"HFS": "/opt/hfs", "PATH": "/opt/hfs/bin"},
        lock_timeout_seconds=8.0,
    )


def _submission(
    *,
    source: str = "print('hello')\n",
    argv: tuple[str, ...] = ("script.py",),
    environment: dict[str, str] | None = None,
) -> TaskSubmission:
    return TaskSubmission(
        source=source,
        file_path="/workspace/script.py",
        argv=argv,
        purpose="build cache",
        origin_cwd="/workspace",
        dispatch=_dispatch(environment),
        history_enabled=True,
    )


def _store(tmp_path: Path, generator: FixedSemanticGenerator | None = None) -> TaskStore:
    return TaskStore(
        tmp_path / "tasks.db",
        semantic_generator=generator or FixedSemanticGenerator(),
        now=lambda: datetime(2026, 9, 11, 8, 0, tzinfo=timezone.utc),
    )


def test_submission_uses_source_only_for_semantic_base_and_task_owned_ordinal(tmp_path: Path) -> None:
    generator = FixedSemanticGenerator()
    store = _store(tmp_path, generator)

    first = store.submit(_submission(argv=("script.py", "--quality", "low")))
    second = store.submit(_submission(argv=("script.py", "--quality", "high")))

    assert first.id == "geometry-build-cache-000"
    assert second.id == "geometry-build-cache-001"
    assert first.semantic_base == second.semantic_base == "geometry-build-cache"
    assert generator.calls == [
        ("print('hello')\n", "task-unknown"),
        ("print('hello')\n", "task-unknown"),
    ]



def test_task_supplies_caller_owned_fallback_stem(tmp_path: Path) -> None:
    class FallbackGenerator:
        def generate(self, text: str, *, fallback_stem: str) -> SemanticBase:
            assert text == "# no semantic tags\n"
            assert fallback_stem == "task-unknown"
            return SemanticBase(prefix=fallback_stem, tags=(), used_fallback=True)

    store = TaskStore(tmp_path / "tasks.db", semantic_generator=FallbackGenerator())
    task = store.submit(_submission(source="# no semantic tags\n"))
    assert task.id == "task-unknown-000"


def test_submission_freezes_source_and_dispatch_context(tmp_path: Path) -> None:
    source_path = tmp_path / "work" / "job.py"
    source_path.parent.mkdir()
    source_path.write_text("value = 1\n", encoding="utf-8")
    environment = {"HFS": "/opt/hfs", "PATH": "/opt/hfs/bin"}
    transport = HoudiniTransport(
        "/opt/hfs/bin/hcommand",
        timeout_seconds=15,
        environ=environment,
    )
    resolved = ResolvedSession(
        record=SessionRecord(
            session=7,
            port=17000,
            pid=8123,
            process_start_identity="start-8123",
        ),
        identity=ProcessIdentity(pid=8123, process_start_identity="start-8123"),
        probe=SessionProbeResult(
            pid=8123,
            version="21.0.440",
            license="Houdini FX",
            file=None,
            headless=False,
            open_ports=(17000,),
        ),
    )
    invocation = ExecutionInvocation(
        source=source_path.read_text(encoding="utf-8"),
        source_path=str(source_path),
        argv=(str(source_path), "one"),
        purpose=None,
        origin_cwd=str(source_path.parent),
    )

    submission = freeze_task_submission(
        invocation,
        session=resolved,
        transport=transport,
        lock_timeout_seconds=9,
        history_enabled=False,
    )
    environment["HFS"] = "/changed"
    source_path.write_text("value = 2\n", encoding="utf-8")

    task = _store(tmp_path).submit(submission)
    assert task.source == "value = 1\n"
    assert task.file_path == str(source_path.resolve())
    assert task.origin_cwd == str(source_path.parent.resolve())
    assert task.dispatch.session == 7
    assert task.dispatch.port == 17000
    assert task.dispatch.pid == 8123
    assert task.dispatch.process_start_identity == "start-8123"
    assert task.dispatch.transport_executable == "/opt/hfs/bin/hcommand"
    assert task.dispatch.transport_timeout_seconds == 15
    assert task.dispatch.lock_timeout_seconds == 9
    assert task.dispatch.transport_environment["HFS"] == "/opt/hfs"
    assert task.history_enabled is False


def test_terminal_transition_removes_frozen_source(tmp_path: Path) -> None:
    store = _store(tmp_path)
    failed = store.submit(_submission(source="raise RuntimeError()\n"))
    store.mark_runtime_failed(failed.id, code="target_changed", message="target changed")
    failed_after = store.get(failed.id)
    assert failed_after is not None
    assert failed_after.status == "failed"
    assert failed_after.source is None
    assert failed_after.runtime_failure_code == "target_changed"

    running = store.submit(_submission(source="print('ok')\n"))
    store.mark_running(running.id)
    store.mark_completed(running.id, completion_resource_id="resource-abc-000")
    completed = store.get(running.id)
    assert completed is not None
    assert completed.status == "completed"
    assert completed.source is None
    assert completed.completion_resource_id == "resource-abc-000"


def test_schema_allows_exactly_four_public_states(tmp_path: Path) -> None:
    store = _store(tmp_path)
    task = store.submit(_submission())
    connection = sqlite3.connect(store.database)
    try:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("UPDATE tasks SET status = 'cancelled' WHERE id = ?", (task.id,))
    finally:
        connection.close()


def test_stream_chunks_append_without_rewriting_prior_output(tmp_path: Path) -> None:
    store = _store(tmp_path)
    task = store.submit(_submission())

    assert store.append_stream(task.id, "stdout", "one\n") == 0
    assert store.append_stream(task.id, "stderr", "warn\n") == 1
    assert store.append_stream(task.id, "stdout", "two\n") == 2
    assert store.accumulated_stream(task.id, "stdout") == "one\ntwo\n"
    assert store.accumulated_stream(task.id, "stderr") == "warn\n"

    with sqlite3.connect(store.database) as connection:
        rows = connection.execute(
            "SELECT sequence, stream, content FROM task_stream_chunks WHERE task_id = ? ORDER BY sequence",
            (task.id,),
        ).fetchall()
    assert rows == [(0, "stdout", "one\n"), (1, "stderr", "warn\n"), (2, "stdout", "two\n")]


def test_ordinal_state_survives_task_row_retention(tmp_path: Path) -> None:
    store = _store(tmp_path)
    first = store.submit(_submission())
    second = store.submit(_submission())

    with sqlite3.connect(store.database) as connection:
        connection.execute("DELETE FROM tasks WHERE id IN (?, ?)", (first.id, second.id))
        connection.commit()

    third = store.submit(_submission())
    assert third.id == "geometry-build-cache-002"


def test_concurrent_submissions_allocate_distinct_ordinals(tmp_path: Path) -> None:
    database = tmp_path / "tasks.db"
    store = TaskStore(database, semantic_generator=FixedSemanticGenerator())

    def submit_one(index: int) -> str:
        return store.submit(_submission(argv=("script.py", str(index)))).id

    with ThreadPoolExecutor(max_workers=8) as executor:
        ids = list(executor.map(submit_one, range(12)))

    assert len(set(ids)) == 12
    assert {int(task_id.rsplit("-", 1)[1]) for task_id in ids} == set(range(12))


def test_task_store_from_config_is_global_not_cwd_scoped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    global_config = tmp_path / "config.toml"
    data_dir = tmp_path / "global-data"
    ensure_config_file(global_config)
    config_text = global_config.read_text(encoding="utf-8")
    global_config.write_text(
        config_text.replace('data_dir = ""', f"data_dir = {json.dumps(str(data_dir))}"),
        encoding="utf-8",
    )
    first_cwd = tmp_path / "workspace-a"
    second_cwd = tmp_path / "workspace-b"
    first_cwd.mkdir()
    second_cwd.mkdir()

    monkeypatch.chdir(first_cwd)
    first = TaskStore.from_config(load_config(global_config), semantic_generator=FixedSemanticGenerator())
    monkeypatch.chdir(second_cwd)
    second = TaskStore.from_config(load_config(global_config), semantic_generator=FixedSemanticGenerator())

    assert first.database == second.database == data_dir / "tasks.db"


def test_task_schema_keeps_ordinal_state_separate_from_task_rows(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.submit(_submission())
    with sqlite3.connect(store.database) as connection:
        task_tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'task%'"
            )
        }
    assert task_tables == {
        "tasks",
        "task_semantic_ordinals",
        "task_stream_chunks",
        "task_invocations",
        "task_runtime_ownership",
        "task_claims",
    }
