from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from typing import Callable, Literal

from houbridge.db.connection import connection_scope
from houbridge.errors import BridgeError

from .schema import ensure_task_schema


StreamName = Literal["stdout", "stderr"]


@dataclass(frozen=True, slots=True)
class TaskInvocationState:
    task_id: str
    workspace_path: Path
    dispatch_started_at: str
    stdout_committed_bytes: int
    stderr_committed_bytes: int

    def committed_bytes(self, stream: StreamName) -> int:
        if stream == "stdout":
            return self.stdout_committed_bytes
        if stream == "stderr":
            return self.stderr_committed_bytes
        raise ValueError("stream must be stdout or stderr")


class TaskInvocationStore:
    """Recovery metadata for one Task invocation inside the shared tasks.db."""

    def __init__(
        self,
        database: Path,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.database = database
        self._now = now or (lambda: datetime.now(timezone.utc))
        with self._connect() as connection:
            ensure_task_schema(connection)

    def create(self, task_id: str, workspace_path: Path) -> TaskInvocationState:
        created_at = _as_utc(self._now()).isoformat()
        workspace = str(workspace_path.resolve())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT status FROM tasks WHERE id = ?",
                (task_id,),
            ).fetchone()
            if row is None:
                raise BridgeError("task_not_found", f"Task does not exist: {task_id}")
            if str(row["status"]) != "queued":
                raise BridgeError(
                    "task_state_conflict",
                    f"Task {task_id} cannot establish a new invocation from {row['status']}.",
                )
            try:
                connection.execute(
                    """
                    INSERT INTO task_invocations(task_id, workspace_path, dispatch_started_at)
                    VALUES (?, ?, ?)
                    """,
                    (task_id, workspace, created_at),
                )
            except sqlite3.IntegrityError as exc:
                existing = connection.execute(
                    "SELECT 1 FROM task_invocations WHERE task_id = ?",
                    (task_id,),
                ).fetchone()
                if existing is not None:
                    raise BridgeError(
                        "task_invocation_exists",
                        f"Task {task_id} already has a recoverable invocation.",
                    ) from exc
                raise
        state = self.get(task_id)
        if state is None:  # pragma: no cover - guarded by transaction above.
            raise BridgeError("task_store_failed", "Task invocation state could not be read back.")
        return state

    def get(self, task_id: str) -> TaskInvocationState | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM task_invocations WHERE task_id = ?",
                (task_id,),
            ).fetchone()
        return _row_to_state(row) if row is not None else None

    def terminal_states(self) -> tuple[TaskInvocationState, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT i.*
                FROM task_invocations AS i
                JOIN tasks AS t ON t.id = i.task_id
                WHERE t.status IN ('completed', 'failed')
                ORDER BY t.finished_at, t.id
                """
            ).fetchall()
        return tuple(_row_to_state(row) for row in rows)

    def remove(self, task_id: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM task_invocations WHERE task_id = ?",
                (task_id,),
            )

    def append_transport_chunk(
        self,
        task_id: str,
        stream: StreamName,
        *,
        expected_offset: int,
        consumed_bytes: int,
        content: str,
    ) -> int:
        if stream not in ("stdout", "stderr"):
            raise ValueError("stream must be stdout or stderr")
        if expected_offset < 0 or consumed_bytes <= 0:
            raise ValueError("stream offsets must be non-negative and consumed_bytes must be positive")
        if not isinstance(content, str) or not content:
            raise ValueError("transport stream content must not be empty")
        offset_column = f"{stream}_committed_bytes"
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                f"SELECT {offset_column} FROM task_invocations WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            if row is None:
                raise BridgeError(
                    "task_invocation_missing",
                    f"Task {task_id} has no recoverable invocation state.",
                )
            current_offset = int(row[offset_column])
            if current_offset != expected_offset:
                return current_offset
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
            new_offset = expected_offset + consumed_bytes
            connection.execute(
                f"UPDATE task_invocations SET {offset_column} = ? WHERE task_id = ?",
                (new_offset, task_id),
            )
        return new_offset

    def _connect(self):
        return connection_scope(self.database)


def _row_to_state(row) -> TaskInvocationState:
    return TaskInvocationState(
        task_id=str(row["task_id"]),
        workspace_path=Path(str(row["workspace_path"])),
        dispatch_started_at=str(row["dispatch_started_at"]),
        stdout_committed_bytes=int(row["stdout_committed_bytes"]),
        stderr_committed_bytes=int(row["stderr_committed_bytes"]),
    )


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("Task invocation clock must return a timezone-aware datetime")
    return value.astimezone(timezone.utc)
