from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Literal, Protocol

from houbridge.config import HoubridgeConfig
from houbridge.db.connection import connection_scope
from houbridge.errors import BridgeError
from houbridge.paths import GlobalDataPaths
from houbridge.semantic_id import PotionSemanticBaseGenerator, SemanticBase

from .models import FrozenDispatchContext, TaskRecord, TaskSubmission, TaskStatus
from .schema import ensure_task_schema


_TASK_FALLBACK_STEM = "task-unknown"
_ORDINAL_WIDTH = 3
StreamName = Literal["stdout", "stderr"]


class SemanticBaseGenerator(Protocol):
    def generate(self, text: str, *, fallback_stem: str) -> SemanticBase:
        ...


class TaskStore:
    """Owner of global asynchronous operational state in tasks.db."""

    def __init__(
        self,
        database: Path,
        *,
        semantic_generator: SemanticBaseGenerator | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.database = database
        self._semantic_generator = semantic_generator or PotionSemanticBaseGenerator()
        self._now = now or (lambda: datetime.now(timezone.utc))
        with self._connect() as connection:
            ensure_task_schema(connection)

    @classmethod
    def from_config(
        cls,
        config: HoubridgeConfig,
        *,
        semantic_generator: SemanticBaseGenerator | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> "TaskStore":
        paths = GlobalDataPaths.from_data_dir(config.storage.data_dir)
        return cls(paths.tasks_database, semantic_generator=semantic_generator, now=now)

    def submit(self, submission: TaskSubmission) -> TaskRecord:
        semantic_base = self._semantic_generator.generate(
            submission.source,
            fallback_stem=_TASK_FALLBACK_STEM,
        )
        source_sha256 = hashlib.sha256(submission.source.encode("utf-8")).hexdigest()
        created_at = _as_utc(self._now()).isoformat()
        dispatch = submission.dispatch
        argv_json = json.dumps(submission.argv, ensure_ascii=False, separators=(",", ":"))
        environment_json = json.dumps(
            dict(dispatch.transport_environment),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            ordinal = _allocate_ordinal(connection, semantic_base.prefix)
            task_id = f"{semantic_base.prefix}-{ordinal:0{_ORDINAL_WIDTH}d}"
            connection.execute(
                """
                INSERT INTO tasks(
                    id,
                    semantic_base,
                    ordinal,
                    status,
                    source,
                    source_sha256,
                    file_path,
                    argv_json,
                    purpose,
                    origin_cwd,
                    target_session,
                    target_port,
                    target_pid,
                    target_process_start_identity,
                    transport_executable,
                    transport_timeout_seconds,
                    transport_environment_json,
                    lock_timeout_seconds,
                    history_enabled,
                    created_at
                ) VALUES (?, ?, ?, 'queued', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    semantic_base.prefix,
                    ordinal,
                    submission.source,
                    source_sha256,
                    submission.file_path,
                    argv_json,
                    submission.purpose,
                    submission.origin_cwd,
                    dispatch.session,
                    dispatch.port,
                    dispatch.pid,
                    dispatch.process_start_identity,
                    dispatch.transport_executable,
                    dispatch.transport_timeout_seconds,
                    environment_json,
                    dispatch.lock_timeout_seconds,
                    int(submission.history_enabled),
                    created_at,
                ),
            )

        record = self.get(task_id)
        if record is None:  # pragma: no cover - guarded by the transaction above.
            raise BridgeError("task_store_failed", "Submitted Task could not be read back.")
        return record

    def get(self, task_id: str) -> TaskRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM tasks WHERE id = ?",
                (task_id,),
            ).fetchone()
        return _row_to_task(row) if row is not None else None

    def append_stream(self, task_id: str, stream: StreamName, content: str) -> int:
        if stream not in ("stdout", "stderr"):
            raise ValueError("stream must be stdout or stderr")
        if not isinstance(content, str):
            raise TypeError("content must be a string")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if connection.execute("SELECT 1 FROM tasks WHERE id = ?", (task_id,)).fetchone() is None:
                raise BridgeError("task_not_found", f"Task does not exist: {task_id}")
            sequence = int(
                connection.execute(
                    "SELECT COALESCE(MAX(sequence), -1) + 1 FROM task_stream_chunks WHERE task_id = ?",
                    (task_id,),
                ).fetchone()[0]
            )
            connection.execute(
                "INSERT INTO task_stream_chunks(task_id, sequence, stream, content) VALUES (?, ?, ?, ?)",
                (task_id, sequence, stream, content),
            )
        return sequence

    def accumulated_stream(self, task_id: str, stream: StreamName) -> str:
        if stream not in ("stdout", "stderr"):
            raise ValueError("stream must be stdout or stderr")
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT content
                FROM task_stream_chunks
                WHERE task_id = ? AND stream = ?
                ORDER BY sequence
                """,
                (task_id, stream),
            ).fetchall()
        return "".join(str(row["content"]) for row in rows)

    def mark_running(self, task_id: str, *, started_at: datetime | None = None) -> None:
        timestamp = _as_utc(started_at or self._now()).isoformat()
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE tasks SET status = 'running', started_at = ? WHERE id = ? AND status = 'queued'",
                (timestamp, task_id),
            )
            if cursor.rowcount != 1:
                _raise_transition_error(connection, task_id, "running")

    def mark_completed(
        self,
        task_id: str,
        *,
        completion_resource_id: str | None = None,
        finished_at: datetime | None = None,
    ) -> None:
        self._mark_terminal(
            task_id,
            status="completed",
            completion_resource_id=completion_resource_id,
            failure=None,
            finished_at=finished_at,
            allowed_from=("running",),
        )

    def mark_python_failed(
        self,
        task_id: str,
        *,
        finished_at: datetime | None = None,
    ) -> None:
        self._mark_terminal(
            task_id,
            status="failed",
            completion_resource_id=None,
            failure=None,
            finished_at=finished_at,
            allowed_from=("running",),
        )

    def mark_runtime_failed(
        self,
        task_id: str,
        *,
        code: str,
        message: str,
        detail: str | None = None,
        finished_at: datetime | None = None,
    ) -> None:
        if not code.strip() or not message.strip():
            raise ValueError("Task failure code and message must not be empty")
        self._mark_terminal(
            task_id,
            status="failed",
            completion_resource_id=None,
            failure=(code, message, detail),
            finished_at=finished_at,
            allowed_from=("queued", "running"),
        )

    def _mark_terminal(
        self,
        task_id: str,
        *,
        status: Literal["completed", "failed"],
        completion_resource_id: str | None,
        failure: tuple[str, str, str | None] | None,
        finished_at: datetime | None,
        allowed_from: tuple[TaskStatus, ...],
    ) -> None:
        timestamp = _as_utc(finished_at or self._now()).isoformat()
        code, message, detail = failure or (None, None, None)
        placeholders = ",".join("?" for _ in allowed_from)
        with self._connect() as connection:
            cursor = connection.execute(
                f"""
                UPDATE tasks
                SET
                    status = ?,
                    source = NULL,
                    finished_at = ?,
                    completion_resource_id = ?,
                    runtime_failure_code = ?,
                    runtime_failure_message = ?,
                    runtime_failure_detail = ?
                WHERE id = ? AND status IN ({placeholders})
                """,
                (
                    status,
                    timestamp,
                    completion_resource_id,
                    code,
                    message,
                    detail,
                    task_id,
                    *allowed_from,
                ),
            )
            if cursor.rowcount != 1:
                _raise_transition_error(connection, task_id, status)

    def _connect(self):
        return connection_scope(self.database)


def _allocate_ordinal(connection: sqlite3.Connection, semantic_base: str) -> int:
    row = connection.execute(
        "SELECT next_ordinal FROM task_semantic_ordinals WHERE semantic_base = ?",
        (semantic_base,),
    ).fetchone()
    if row is None:
        connection.execute(
            "INSERT INTO task_semantic_ordinals(semantic_base, next_ordinal) VALUES (?, 1)",
            (semantic_base,),
        )
        return 0
    ordinal = int(row["next_ordinal"])
    connection.execute(
        "UPDATE task_semantic_ordinals SET next_ordinal = ? WHERE semantic_base = ?",
        (ordinal + 1, semantic_base),
    )
    return ordinal


def _row_to_task(row: sqlite3.Row) -> TaskRecord:
    try:
        argv_raw = json.loads(str(row["argv_json"]))
        environment_raw = json.loads(str(row["transport_environment_json"]))
    except json.JSONDecodeError as exc:  # pragma: no cover - database corruption guard.
        raise BridgeError("task_store_invalid", "Stored Task JSON metadata is invalid.", str(exc)) from exc
    if not isinstance(argv_raw, list) or not all(isinstance(value, str) for value in argv_raw):
        raise BridgeError("task_store_invalid", "Stored Task argv metadata is invalid.")
    if not isinstance(environment_raw, dict) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in environment_raw.items()
    ):
        raise BridgeError("task_store_invalid", "Stored Task transport environment is invalid.")

    status = str(row["status"])
    if status not in ("queued", "running", "completed", "failed"):
        raise BridgeError("task_store_invalid", f"Stored Task status is invalid: {status}")

    return TaskRecord(
        id=str(row["id"]),
        semantic_base=str(row["semantic_base"]),
        ordinal=int(row["ordinal"]),
        status=status,  # type: ignore[arg-type]
        source=(str(row["source"]) if row["source"] is not None else None),
        source_sha256=str(row["source_sha256"]),
        file_path=str(row["file_path"]),
        argv=tuple(argv_raw),
        purpose=(str(row["purpose"]) if row["purpose"] is not None else None),
        origin_cwd=str(row["origin_cwd"]),
        dispatch=FrozenDispatchContext(
            session=int(row["target_session"]),
            port=int(row["target_port"]),
            pid=int(row["target_pid"]),
            process_start_identity=str(row["target_process_start_identity"]),
            transport_executable=str(row["transport_executable"]),
            transport_timeout_seconds=float(row["transport_timeout_seconds"]),
            transport_environment=environment_raw,
            lock_timeout_seconds=float(row["lock_timeout_seconds"]),
        ),
        created_at=str(row["created_at"]),
        started_at=(str(row["started_at"]) if row["started_at"] is not None else None),
        finished_at=(str(row["finished_at"]) if row["finished_at"] is not None else None),
        completion_resource_id=(
            str(row["completion_resource_id"])
            if row["completion_resource_id"] is not None
            else None
        ),
        history_enabled=bool(row["history_enabled"]),
        runtime_failure_code=(
            str(row["runtime_failure_code"]) if row["runtime_failure_code"] is not None else None
        ),
        runtime_failure_message=(
            str(row["runtime_failure_message"])
            if row["runtime_failure_message"] is not None
            else None
        ),
        runtime_failure_detail=(
            str(row["runtime_failure_detail"])
            if row["runtime_failure_detail"] is not None
            else None
        ),
    )


def _raise_transition_error(connection: sqlite3.Connection, task_id: str, target: str) -> None:
    row = connection.execute("SELECT status FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if row is None:
        raise BridgeError("task_not_found", f"Task does not exist: {task_id}")
    raise BridgeError(
        "task_state_conflict",
        f"Task {task_id} cannot transition from {row['status']} to {target}.",
    )


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("Task clock must return a timezone-aware datetime")
    return value.astimezone(timezone.utc)
