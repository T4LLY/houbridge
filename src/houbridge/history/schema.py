from __future__ import annotations

import sqlite3


SCHEMA_VERSION = "1"


def initialize_history_schema(connection: sqlite3.Connection) -> None:
    """Create only the current session Action History schema."""

    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS history_metadata(
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        ) WITHOUT ROWID;

        CREATE TABLE IF NOT EXISTS history_id_sequence(
            singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
            next_id INTEGER NOT NULL CHECK(next_id > 0)
        );

        INSERT OR IGNORE INTO history_id_sequence(singleton, next_id)
        VALUES (1, 1);

        CREATE TABLE IF NOT EXISTS history_entries(
            id INTEGER PRIMARY KEY,
            time TEXT NOT NULL,
            cwd TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('completed', 'failed')),
            file TEXT NOT NULL,
            args_json TEXT NOT NULL,
            purpose TEXT,
            source_hash TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS history_changes(
            entry_id INTEGER NOT NULL,
            ordinal INTEGER NOT NULL CHECK(ordinal >= 0),
            node_session_id INTEGER NOT NULL,
            payload_json TEXT NOT NULL,
            PRIMARY KEY(entry_id, ordinal),
            FOREIGN KEY(entry_id) REFERENCES history_entries(id) ON DELETE CASCADE
        ) WITHOUT ROWID;

        CREATE INDEX IF NOT EXISTS history_changes_node_session_lookup
        ON history_changes(node_session_id);
        """
    )
    connection.execute(
        """
        INSERT INTO history_metadata(key, value)
        VALUES ('schema_version', ?)
        ON CONFLICT(key) DO NOTHING
        """,
        (SCHEMA_VERSION,),
    )
