from __future__ import annotations

import sqlite3


_TASK_SCHEMA = """
CREATE TABLE IF NOT EXISTS task_semantic_ordinals (
    semantic_base TEXT PRIMARY KEY NOT NULL,
    next_ordinal INTEGER NOT NULL CHECK (next_ordinal >= 0)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY NOT NULL,
    semantic_base TEXT NOT NULL,
    ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
    status TEXT NOT NULL CHECK (status IN ('queued', 'running', 'completed', 'failed')),
    source TEXT,
    source_sha256 TEXT NOT NULL,
    file_path TEXT NOT NULL,
    argv_json TEXT NOT NULL,
    purpose TEXT,
    origin_cwd TEXT NOT NULL,
    target_session INTEGER NOT NULL CHECK (target_session > 0),
    target_port INTEGER NOT NULL CHECK (target_port BETWEEN 1 AND 65535),
    target_pid INTEGER NOT NULL CHECK (target_pid > 0),
    target_process_start_identity TEXT NOT NULL,
    transport_executable TEXT NOT NULL,
    transport_timeout_seconds REAL NOT NULL CHECK (transport_timeout_seconds > 0),
    transport_environment_json TEXT NOT NULL,
    lock_timeout_seconds REAL NOT NULL CHECK (lock_timeout_seconds > 0),
    history_enabled INTEGER NOT NULL CHECK (history_enabled IN (0, 1)),
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    completion_resource_id TEXT,
    runtime_failure_code TEXT,
    runtime_failure_message TEXT,
    runtime_failure_detail TEXT,
    UNIQUE(semantic_base, ordinal)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS task_stream_chunks (
    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    sequence INTEGER NOT NULL CHECK (sequence >= 0),
    stream TEXT NOT NULL CHECK (stream IN ('stdout', 'stderr')),
    content TEXT NOT NULL,
    PRIMARY KEY(task_id, sequence)
) WITHOUT ROWID;

CREATE INDEX IF NOT EXISTS task_status_created_idx
ON tasks(status, created_at, id);
"""


def ensure_task_schema(connection: sqlite3.Connection) -> None:
    """Create only Task-owned persistence in the global tasks.db."""

    connection.executescript(_TASK_SCHEMA)
