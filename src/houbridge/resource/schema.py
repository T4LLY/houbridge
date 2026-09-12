from __future__ import annotations

import sqlite3


_RESOURCE_SCHEMA = """
CREATE TABLE IF NOT EXISTS resources (
    canonical_id TEXT PRIMARY KEY NOT NULL,
    content_class TEXT NOT NULL CHECK (content_class IN ('binary', 'text', 'json')),
    mime TEXT NOT NULL,
    byte_size INTEGER NOT NULL CHECK (byte_size >= 0),
    token_count INTEGER CHECK (token_count IS NULL OR token_count >= 0),
    created_at TEXT NOT NULL,
    payload BLOB NOT NULL
) WITHOUT ROWID;
"""


def ensure_resource_schema(connection: sqlite3.Connection) -> None:
    """Create only Resource-owned persistence in global resources.db."""

    connection.executescript(_RESOURCE_SCHEMA)
