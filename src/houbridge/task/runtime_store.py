from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from houbridge.config import HoubridgeConfig
from houbridge.db.connection import connection_scope
from houbridge.errors import BridgeError
from houbridge.paths import GlobalDataPaths
from houbridge.process_coordination import ProcessIdentity

from .schema import ensure_task_schema


@dataclass(frozen=True, slots=True)
class RuntimeOwner:
    token: str
    starter_identity: ProcessIdentity
    runtime_identity: ProcessIdentity | None
    acquired_at: str


class TaskRuntimeStateStore:
    """Task-owned runtime ownership and claim state in the shared tasks.db."""

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

    @classmethod
    def from_config(
        cls,
        config: HoubridgeConfig,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> "TaskRuntimeStateStore":
        paths = GlobalDataPaths.from_data_dir(config.storage.data_dir)
        return cls(paths.tasks_database, now=now)

    def recoverable_work_exists(self) -> bool:
        with self._connect() as connection:
            return (
                connection.execute(
                    """
                    SELECT 1
                    WHERE EXISTS (SELECT 1 FROM tasks WHERE status IN ('queued', 'running'))
                       OR EXISTS (SELECT 1 FROM task_invocations)
                    """
                ).fetchone()
                is not None
            )

    def runtime_owner(self) -> RuntimeOwner | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM task_runtime_ownership WHERE singleton = 1"
            ).fetchone()
        if row is None:
            return None
        runtime_identity = None
        if row["runtime_pid"] is not None:
            runtime_identity = ProcessIdentity(
                pid=int(row["runtime_pid"]),
                process_start_identity=str(row["runtime_process_start_identity"]),
            )
        return RuntimeOwner(
            token=str(row["token"]),
            starter_identity=ProcessIdentity(
                pid=int(row["starter_pid"]),
                process_start_identity=str(row["starter_process_start_identity"]),
            ),
            runtime_identity=runtime_identity,
            acquired_at=str(row["acquired_at"]),
        )

    def reserve_runtime_start(self, token: str, starter_identity: ProcessIdentity) -> bool:
        token = token.strip()
        if not token:
            raise ValueError("runtime owner token must not be empty")
        acquired_at = _as_utc(self._now()).isoformat()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if connection.execute(
                "SELECT 1 FROM task_runtime_ownership WHERE singleton = 1"
            ).fetchone() is not None:
                return False
            connection.execute(
                """
                INSERT INTO task_runtime_ownership(
                    singleton, token, starter_pid, starter_process_start_identity, acquired_at
                ) VALUES (1, ?, ?, ?, ?)
                """,
                (
                    token,
                    starter_identity.pid,
                    starter_identity.process_start_identity,
                    acquired_at,
                ),
            )
        return True

    def claim_runtime_owner(self, token: str, runtime_identity: ProcessIdentity) -> bool:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                """
                UPDATE task_runtime_ownership
                SET runtime_pid = ?, runtime_process_start_identity = ?
                WHERE singleton = 1 AND token = ?
                """,
                (runtime_identity.pid, runtime_identity.process_start_identity, token),
            )
            return cursor.rowcount == 1

    def clear_runtime_owner(self, token: str) -> bool:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                "DELETE FROM task_runtime_ownership WHERE singleton = 1 AND token = ?",
                (token,),
            )
            return cursor.rowcount == 1

    def retire_runtime_if_idle(self, token: str) -> bool:
        """Release ownership atomically only while no active Task work exists."""

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            _require_runtime_owner(connection, token)
            if connection.execute(
                """
                SELECT 1
                WHERE EXISTS (SELECT 1 FROM tasks WHERE status IN ('queued', 'running'))
                   OR EXISTS (SELECT 1 FROM task_invocations)
                """
            ).fetchone() is not None:
                return False
            connection.execute(
                "DELETE FROM task_runtime_ownership WHERE singleton = 1 AND token = ?",
                (token,),
            )
            return True

    def adopt_runtime_claims(self, owner_token: str) -> tuple[str, ...]:
        """Transfer stale running claims while releasing only safe queued claims."""

        claimed_at = _as_utc(self._now()).isoformat()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            _require_runtime_owner(connection, owner_token)
            _delete_terminal_claims(connection)
            connection.execute(
                """
                DELETE FROM task_claims
                WHERE owner_token <> ?
                  AND task_id IN (
                      SELECT t.id
                      FROM tasks AS t
                      WHERE t.status = 'queued'
                        AND NOT EXISTS (
                            SELECT 1 FROM task_invocations AS i WHERE i.task_id = t.id
                        )
                  )
                """,
                (owner_token,),
            )
            connection.execute(
                """
                UPDATE task_claims
                SET owner_token = ?, claimed_at = ?
                WHERE owner_token <> ?
                  AND task_id IN (
                      SELECT t.id
                      FROM tasks AS t
                      WHERE t.status = 'running'
                         OR (
                             t.status = 'queued'
                             AND EXISTS (
                                 SELECT 1 FROM task_invocations AS i WHERE i.task_id = t.id
                             )
                         )
                  )
                """,
                (owner_token, claimed_at, owner_token),
            )
            connection.execute(
                """
                INSERT OR IGNORE INTO task_claims(
                    task_id, owner_token, target_pid, target_process_start_identity, claimed_at
                )
                SELECT t.id, ?, t.target_pid, t.target_process_start_identity, ?
                FROM tasks AS t
                WHERE t.status = 'running'
                   OR (
                       t.status = 'queued'
                       AND EXISTS (
                           SELECT 1 FROM task_invocations AS i WHERE i.task_id = t.id
                       )
                   )
                """,
                (owner_token, claimed_at),
            )
            rows = connection.execute(
                """
                SELECT t.id
                FROM tasks AS t
                JOIN task_claims AS c ON c.task_id = t.id
                WHERE c.owner_token = ?
                  AND (
                      t.status = 'running'
                      OR (
                          t.status = 'queued'
                          AND EXISTS (
                              SELECT 1 FROM task_invocations AS i WHERE i.task_id = t.id
                          )
                      )
                  )
                ORDER BY t.created_at, t.id
                """,
                (owner_token,),
            ).fetchall()
        return tuple(str(row["id"]) for row in rows)

    def claim_next_queued(self, owner_token: str, *, max_concurrency: int) -> str | None:
        if (
            isinstance(max_concurrency, bool)
            or not isinstance(max_concurrency, int)
            or max_concurrency < 1
        ):
            raise ValueError("max_concurrency must be an integer >= 1")
        claimed_at = _as_utc(self._now()).isoformat()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            _require_runtime_owner(connection, owner_token)
            _delete_terminal_claims(connection)
            in_use = int(
                connection.execute(
                    """
                    SELECT COUNT(*)
                    FROM task_claims AS c
                    JOIN tasks AS t ON t.id = c.task_id
                    WHERE t.status IN ('queued', 'running')
                    """
                ).fetchone()[0]
            )
            if in_use >= max_concurrency:
                return None
            row = connection.execute(
                """
                SELECT t.id, t.target_pid, t.target_process_start_identity
                FROM tasks AS t
                WHERE t.status = 'queued'
                  AND NOT EXISTS (SELECT 1 FROM task_claims AS c WHERE c.task_id = t.id)
                  AND NOT EXISTS (
                      SELECT 1
                      FROM task_claims AS c
                      JOIN tasks AS active ON active.id = c.task_id
                      WHERE active.status IN ('queued', 'running')
                        AND c.target_pid = t.target_pid
                        AND c.target_process_start_identity = t.target_process_start_identity
                  )
                ORDER BY t.created_at, t.id
                LIMIT 1
                """
            ).fetchone()
            if row is None:
                return None
            task_id = str(row["id"])
            connection.execute(
                """
                INSERT INTO task_claims(
                    task_id, owner_token, target_pid, target_process_start_identity, claimed_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    owner_token,
                    int(row["target_pid"]),
                    str(row["target_process_start_identity"]),
                    claimed_at,
                ),
            )
            return task_id

    def recoverable_claims_for_owner(self, owner_token: str) -> tuple[str, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT t.id
                FROM tasks AS t
                JOIN task_claims AS c ON c.task_id = t.id
                WHERE c.owner_token = ?
                  AND (
                      t.status = 'running'
                      OR (
                          t.status = 'queued'
                          AND EXISTS (
                              SELECT 1 FROM task_invocations AS i WHERE i.task_id = t.id
                          )
                      )
                  )
                ORDER BY t.created_at, t.id
                """,
                (owner_token,),
            ).fetchall()
        return tuple(str(row["id"]) for row in rows)

    def release_claim(self, task_id: str, owner_token: str) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM task_claims WHERE task_id = ? AND owner_token = ?",
                (task_id, owner_token),
            )
            return cursor.rowcount == 1

    def claim_count(self) -> int:
        with self._connect() as connection:
            return int(connection.execute("SELECT COUNT(*) FROM task_claims").fetchone()[0])

    def _connect(self):
        return connection_scope(self.database)


def _delete_terminal_claims(connection) -> None:
    connection.execute(
        """
        DELETE FROM task_claims
        WHERE task_id IN (SELECT id FROM tasks WHERE status IN ('completed', 'failed'))
        """
    )


def _require_runtime_owner(connection, owner_token: str) -> None:
    row = connection.execute(
        "SELECT token FROM task_runtime_ownership WHERE singleton = 1"
    ).fetchone()
    if row is None or str(row["token"]) != owner_token:
        raise BridgeError(
            "task_runtime_ownership_lost",
            "Task Runtime no longer owns the global Task store.",
        )


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("Task runtime clock must return a timezone-aware datetime")
    return value.astimezone(timezone.utc)
