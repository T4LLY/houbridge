from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from houbridge.config import HoubridgeConfig
from houbridge.db.connection import connection_scope
from houbridge.errors import BridgeError
from houbridge.output.tokens import FallbackTokenEstimator, TokenEstimator
from houbridge.paths import GlobalDataPaths
from houbridge.resource.classifier import classify_content
from houbridge.resource.models import Resource
from houbridge.resource.schema import ensure_resource_schema


class ResourceStore:
    """Global, database-complete canonical Resource payload store."""

    def __init__(
        self,
        database: Path,
        *,
        token_estimator: TokenEstimator | None = None,
    ) -> None:
        self.database = database
        self._token_estimator = token_estimator or FallbackTokenEstimator()
        with self._connect() as connection:
            ensure_resource_schema(connection)

    @classmethod
    def from_config(
        cls,
        config: HoubridgeConfig,
        *,
        token_estimator: TokenEstimator | None = None,
    ) -> "ResourceStore":
        paths = GlobalDataPaths.from_data_dir(config.storage.data_dir)
        return cls(paths.resources_database, token_estimator=token_estimator)

    def put_bytes(self, payload: bytes) -> Resource:
        classification = classify_content(payload)
        canonical_id = hashlib.sha256(payload).hexdigest()
        token_count = (
            self._token_estimator.count(classification.decoded_text)
            if classification.decoded_text is not None
            else None
        )
        created_at = _utc_now()

        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO resources(
                    canonical_id,
                    content_class,
                    mime,
                    byte_size,
                    token_count,
                    created_at,
                    payload
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    canonical_id,
                    classification.content_class,
                    classification.mime,
                    len(payload),
                    token_count,
                    created_at,
                    sqlite3.Binary(payload),
                ),
            )
            row = connection.execute(
                """
                SELECT canonical_id, content_class, mime, byte_size, token_count, created_at
                FROM resources
                WHERE canonical_id = ?
                """,
                (canonical_id,),
            ).fetchone()

        if row is None:
            raise BridgeError(
                "resource_store_failed",
                "Resource payload could not be stored.",
            )
        return _row_to_resource(row)

    def put_text(self, text: str) -> Resource:
        return self.put_bytes(text.encode("utf-8"))

    def put_json(self, value: Any) -> Resource:
        payload = json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return self.put_bytes(payload)

    def get(self, canonical_id: str) -> Resource | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT canonical_id, content_class, mime, byte_size, token_count, created_at
                FROM resources
                WHERE canonical_id = ?
                """,
                (canonical_id,),
            ).fetchone()
        return _row_to_resource(row) if row is not None else None

    def get_bytes(self, canonical_id: str) -> bytes | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM resources WHERE canonical_id = ?",
                (canonical_id,),
            ).fetchone()
        return bytes(row["payload"]) if row is not None else None

    def _connect(self):
        return connection_scope(self.database)


def _row_to_resource(row: sqlite3.Row) -> Resource:
    return Resource(
        canonical_id=str(row["canonical_id"]),
        content_class=row["content_class"],
        mime=str(row["mime"]),
        byte_size=int(row["byte_size"]),
        token_count=(int(row["token_count"]) if row["token_count"] is not None else None),
        created_at=str(row["created_at"]),
    )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
