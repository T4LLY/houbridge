from __future__ import annotations

import re
import sqlite3
from collections.abc import Sequence


_INLINE_MEMBERSHIP_LIMIT = 256
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")


def quote_identifier(value: str) -> str:
    """Return one validated SQLite identifier quoted for SQL composition."""

    if not _IDENTIFIER.fullmatch(value):
        raise ValueError(f"invalid SQLite identifier: {value!r}")
    return f'"{value}"'


def append_membership_filter(
    connection: sqlite3.Connection,
    where: list[str],
    params: list[object],
    *,
    column: str,
    values: Sequence[str] | None,
    temp_table: str,
) -> None:
    """Append a bounded or temp-table membership predicate.

    The caller owns the database and the surrounding query. This helper owns no
    persistent schema; large filters use a connection-local TEMP table only.
    """

    members = [str(value) for value in values or ()]
    if not members:
        return

    quoted_column = _quote_column_reference(column)
    if len(members) <= _INLINE_MEMBERSHIP_LIMIT:
        placeholders = ",".join("?" for _ in members)
        where.append(f"{quoted_column} IN ({placeholders})")
        params.extend(members)
        return

    quoted_table = quote_identifier(temp_table)
    connection.execute(
        f"CREATE TEMP TABLE IF NOT EXISTS {quoted_table}"
        "(value TEXT PRIMARY KEY) WITHOUT ROWID"
    )
    connection.execute(f"DELETE FROM {quoted_table}")
    connection.executemany(
        f"INSERT OR IGNORE INTO {quoted_table}(value) VALUES (?)",
        [(value,) for value in members],
    )
    where.append(f"{quoted_column} IN (SELECT value FROM {quoted_table})")


def _quote_column_reference(value: str) -> str:
    parts = value.split(".")
    if not parts or any(not _IDENTIFIER.fullmatch(part) for part in parts):
        raise ValueError(f"invalid SQLite column reference: {value!r}")
    return ".".join(f'"{part}"' for part in parts)
