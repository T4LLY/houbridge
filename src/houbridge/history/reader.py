from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

from houbridge.history.locking import (
    HistoryDatabaseMissingError,
    history_connection_scope,
)
from houbridge.errors import BridgeError
from houbridge.formatting import format_public_datetime


@dataclass(frozen=True, slots=True)
class HistoryEntryRecord:
    id: int
    time: str
    cwd: str
    status: str
    file: str
    args: tuple[str, ...]
    purpose: str | None
    source_hash: str
    changes: tuple[dict[str, object], ...]

    def public_full(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "id": self.id,
            "time": _public_time(self.time),
            "status": self.status,
            "cwd": self.cwd,
            "file": self.file,
            "args": list(self.args),
        }
        if self.purpose:
            payload["purpose"] = self.purpose
        payload["changes"] = [dict(change) for change in self.changes]
        return payload

    def public_list_item(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "id": self.id,
            "time": _public_time(self.time),
            "status": self.status,
            "file": self.file,
        }
        if self.purpose:
            payload["purpose"] = self.purpose
        return payload


class HistoryReader:
    """Read complete Action History records from one exact session database."""

    def __init__(self, database: Path, *, lock_timeout_seconds: float = 120.0) -> None:
        self._database = database
        self._lock_timeout_seconds = float(lock_timeout_seconds)

    def get(self, history_id: int) -> HistoryEntryRecord | None:
        try:
            with history_connection_scope(
                self._database,
                require_existing=True,
                lock_timeout_seconds=self._lock_timeout_seconds,
            ) as connection:
                row = connection.execute(
                    "SELECT * FROM history_entries WHERE id = ?",
                    (history_id,),
                ).fetchone()
                if row is None:
                    return None
                changes = connection.execute(
                    """
                    SELECT payload_json
                    FROM history_changes
                    WHERE entry_id = ?
                    ORDER BY ordinal ASC
                    """,
                    (history_id,),
                ).fetchall()
        except HistoryDatabaseMissingError:
            return None
        except sqlite3.Error as exc:
            raise _database_error(exc) from exc
        return _decode_entry(row, changes)

    def list(self, limit: int) -> list[HistoryEntryRecord]:
        try:
            with history_connection_scope(
                self._database,
                require_existing=True,
                lock_timeout_seconds=self._lock_timeout_seconds,
            ) as connection:
                rows = connection.execute(
                    """
                    SELECT *
                    FROM history_entries
                    ORDER BY time DESC, id DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
        except HistoryDatabaseMissingError:
            return []
        except sqlite3.Error as exc:
            raise _database_error(exc) from exc
        return [_decode_entry(row, ()) for row in rows]

    def all_for_search(self) -> list[HistoryEntryRecord]:
        try:
            with history_connection_scope(
                self._database,
                require_existing=True,
                lock_timeout_seconds=self._lock_timeout_seconds,
            ) as connection:
                rows = connection.execute(
                    """
                    SELECT *
                    FROM history_entries
                    ORDER BY id ASC
                    """
                ).fetchall()
                change_rows = connection.execute(
                    """
                    SELECT entry_id, payload_json
                    FROM history_changes
                    ORDER BY entry_id ASC, ordinal ASC
                    """
                ).fetchall()
        except HistoryDatabaseMissingError:
            return []
        except sqlite3.Error as exc:
            raise _database_error(exc) from exc

        changes_by_entry: dict[int, list[sqlite3.Row]] = {}
        for change in change_rows:
            changes_by_entry.setdefault(int(change["entry_id"]), []).append(change)
        return [
            _decode_entry(row, changes_by_entry.get(int(row["id"]), ()))
            for row in rows
        ]


class HistoryReadService:
    def __init__(self, reader: HistoryReader | None) -> None:
        self._reader = reader

    def get(self, history_id: int) -> dict[str, object]:
        if history_id <= 0:
            raise BridgeError("invalid_history_id", "HISTORY_ID must be a positive integer.")
        entry = self._reader.get(history_id) if self._reader is not None else None
        if entry is None:
            raise BridgeError(
                "history_not_found",
                f"History entry {history_id} does not exist in the selected session.",
            )
        return entry.public_full()

    def list(self, limit: int) -> dict[str, object]:
        if limit <= 0:
            raise BridgeError("invalid_history_limit", "--limit must be a positive integer.")
        if self._reader is None:
            return {"entries": []}
        return {"entries": [entry.public_list_item() for entry in self._reader.list(limit)]}


def _decode_entry(row: sqlite3.Row, change_rows: Iterable[sqlite3.Row]) -> HistoryEntryRecord:
    try:
        args_raw = json.loads(str(row["args_json"]))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise BridgeError(
            "history_store_invalid",
            "History entry contains invalid argument data.",
            f"entry={row['id']}: {exc}",
        ) from exc
    if not isinstance(args_raw, list) or any(not isinstance(value, str) for value in args_raw):
        raise BridgeError(
            "history_store_invalid",
            "History entry contains invalid argument data.",
            f"entry={row['id']}",
        )

    changes: list[dict[str, object]] = []
    for change_row in change_rows:
        try:
            payload = json.loads(str(change_row["payload_json"]))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise BridgeError(
                "history_store_invalid",
                "History entry contains invalid Action Change data.",
                f"entry={row['id']}: {exc}",
            ) from exc
        if not isinstance(payload, dict):
            raise BridgeError(
                "history_store_invalid",
                "History entry contains invalid Action Change data.",
                f"entry={row['id']}",
            )
        changes.append(payload)

    return HistoryEntryRecord(
        id=int(row["id"]),
        time=str(row["time"]),
        cwd=str(row["cwd"]),
        status=str(row["status"]),
        file=str(row["file"]),
        args=tuple(args_raw),
        purpose=None if row["purpose"] is None else str(row["purpose"]),
        source_hash=str(row["source_hash"]),
        changes=tuple(changes),
    )


def _public_time(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise BridgeError(
            "history_store_invalid",
            "History entry contains an invalid timestamp.",
            value,
        ) from exc
    return format_public_datetime(parsed)


def _database_error(exc: sqlite3.Error) -> BridgeError:
    return BridgeError(
        "history_store_failed",
        "History database operation failed.",
        str(exc),
    )
