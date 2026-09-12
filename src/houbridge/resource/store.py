from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Protocol

from houbridge.config import HoubridgeConfig
from houbridge.db.connection import connection_scope
from houbridge.errors import BridgeError
from houbridge.output.tokens import FallbackTokenEstimator, TokenEstimator
from houbridge.paths import GlobalDataPaths
from houbridge.resource.classifier import ContentClassification, classify_content
from houbridge.resource.models import Resource
from houbridge.resource.schema import ensure_resource_schema
from houbridge.semantic_id import PotionSemanticBaseGenerator, SemanticBase


_RESOURCE_FALLBACK_STEM = "resource-unknown-content"
_DEFAULT_TTL_HOURS = 72
_ORDINAL_WIDTH = 3


class SemanticBaseGenerator(Protocol):
    def generate(self, text: str, *, fallback_stem: str) -> SemanticBase:
        ...


class ResourceStore:
    """Global Resource payload, semantic identity, and retention owner."""

    def __init__(
        self,
        database: Path,
        *,
        ttl_hours: int = _DEFAULT_TTL_HOURS,
        token_estimator: TokenEstimator | None = None,
        semantic_generator: SemanticBaseGenerator | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if ttl_hours < 1:
            raise ValueError("ttl_hours must be >= 1")
        self.database = database
        self.ttl_hours = ttl_hours
        self._token_estimator = token_estimator or FallbackTokenEstimator()
        self._semantic_generator = semantic_generator or PotionSemanticBaseGenerator()
        self._now = now or (lambda: datetime.now(timezone.utc))
        with self._connect() as connection:
            ensure_resource_schema(connection)

    @classmethod
    def from_config(
        cls,
        config: HoubridgeConfig,
        *,
        token_estimator: TokenEstimator | None = None,
        semantic_generator: SemanticBaseGenerator | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> "ResourceStore":
        paths = GlobalDataPaths.from_data_dir(config.storage.data_dir)
        return cls(
            paths.resources_database,
            ttl_hours=config.resource.ttl_hours,
            token_estimator=token_estimator,
            semantic_generator=semantic_generator,
            now=now,
        )

    def put_bytes(self, payload: bytes) -> Resource:
        classification = classify_content(payload)
        canonical_id = hashlib.sha256(payload).hexdigest()
        token_count = (
            self._token_estimator.count(classification.decoded_text)
            if classification.decoded_text is not None
            else None
        )

        known_alias = self._alias_for_canonical(canonical_id)
        semantic_base = None
        if known_alias is None:
            semantic_base = self._semantic_generator.generate(
                _semantic_text(classification),
                fallback_stem=_RESOURCE_FALLBACK_STEM,
            )

        write_time = _as_utc(self._now())
        created_at = write_time.isoformat()
        expires_at = (write_time + timedelta(hours=self.ttl_hours)).isoformat()

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            alias_row = connection.execute(
                """
                SELECT semantic_alias, prefix, ordinal, tags_json
                FROM resource_semantic_aliases
                WHERE canonical_id = ?
                """,
                (canonical_id,),
            ).fetchone()

            if alias_row is None:
                if semantic_base is None:
                    raise BridgeError(
                        "resource_store_failed",
                        "Resource semantic identity could not be allocated.",
                    )
                alias = _allocate_alias(
                    connection,
                    canonical_id=canonical_id,
                    semantic_base=semantic_base,
                )
            else:
                alias = str(alias_row["semantic_alias"])

            connection.execute(
                """
                INSERT INTO resources(
                    canonical_id,
                    content_class,
                    mime,
                    byte_size,
                    token_count,
                    created_at,
                    expires_at,
                    payload
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(canonical_id) DO UPDATE SET
                    content_class = excluded.content_class,
                    mime = excluded.mime,
                    byte_size = excluded.byte_size,
                    token_count = excluded.token_count,
                    expires_at = excluded.expires_at,
                    payload = excluded.payload
                """,
                (
                    canonical_id,
                    classification.content_class,
                    classification.mime,
                    len(payload),
                    token_count,
                    created_at,
                    expires_at,
                    sqlite3.Binary(payload),
                ),
            )
            row = connection.execute(
                """
                SELECT
                    r.canonical_id,
                    a.semantic_alias,
                    r.content_class,
                    r.mime,
                    r.byte_size,
                    r.token_count,
                    r.created_at,
                    r.expires_at
                FROM resources AS r
                JOIN resource_semantic_aliases AS a USING(canonical_id)
                WHERE r.canonical_id = ?
                """,
                (canonical_id,),
            ).fetchone()

        if row is None:
            raise BridgeError(
                "resource_store_failed",
                "Resource payload could not be stored.",
            )
        resource = _row_to_resource(row)
        if resource.semantic_alias != alias:
            raise BridgeError(
                "resource_store_failed",
                "Resource semantic identity changed during storage.",
            )
        return resource

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

    def resolve_canonical_id(self, resource_id: str) -> str | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT canonical_id
                FROM resource_semantic_aliases
                WHERE canonical_id = ? OR semantic_alias = ?
                LIMIT 1
                """,
                (resource_id, resource_id),
            ).fetchone()
        return str(row["canonical_id"]) if row is not None else None

    def get(self, resource_id: str) -> Resource | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT
                    r.canonical_id,
                    a.semantic_alias,
                    r.content_class,
                    r.mime,
                    r.byte_size,
                    r.token_count,
                    r.created_at,
                    r.expires_at
                FROM resource_semantic_aliases AS a
                JOIN resources AS r USING(canonical_id)
                WHERE a.canonical_id = ? OR a.semantic_alias = ?
                LIMIT 1
                """,
                (resource_id, resource_id),
            ).fetchone()
        return _row_to_resource(row) if row is not None else None

    def get_bytes(self, resource_id: str) -> bytes | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT r.payload
                FROM resource_semantic_aliases AS a
                JOIN resources AS r USING(canonical_id)
                WHERE a.canonical_id = ? OR a.semantic_alias = ?
                LIMIT 1
                """,
                (resource_id, resource_id),
            ).fetchone()
        return bytes(row["payload"]) if row is not None else None

    def cleanup_expired(self, *, now: datetime | None = None) -> int:
        cutoff = _as_utc(now or self._now()).isoformat()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                "DELETE FROM resources WHERE expires_at <= ?",
                (cutoff,),
            )
            return max(cursor.rowcount, 0)

    def _alias_for_canonical(self, canonical_id: str) -> str | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT semantic_alias
                FROM resource_semantic_aliases
                WHERE canonical_id = ?
                """,
                (canonical_id,),
            ).fetchone()
        return str(row["semantic_alias"]) if row is not None else None

    def _connect(self):
        return connection_scope(self.database)


def _allocate_alias(
    connection: sqlite3.Connection,
    *,
    canonical_id: str,
    semantic_base: SemanticBase,
) -> str:
    ordinal = int(
        connection.execute(
            """
            SELECT COALESCE(MAX(ordinal), -1) + 1
            FROM resource_semantic_aliases
            WHERE prefix = ?
            """,
            (semantic_base.prefix,),
        ).fetchone()[0]
    )
    semantic_alias = f"{semantic_base.prefix}{ordinal:0{_ORDINAL_WIDTH}d}"
    connection.execute(
        """
        INSERT INTO resource_semantic_aliases(
            canonical_id,
            semantic_alias,
            prefix,
            ordinal,
            tags_json
        ) VALUES (?, ?, ?, ?, ?)
        """,
        (
            canonical_id,
            semantic_alias,
            semantic_base.prefix,
            ordinal,
            json.dumps(semantic_base.tags, ensure_ascii=True, separators=(",", ":")),
        ),
    )
    return semantic_alias


def _semantic_text(classification: ContentClassification) -> str:
    if classification.content_class in ("text", "json"):
        text = classification.decoded_text or ""
        if text.strip():
            return text
    return classification.mime or "resource"


def _row_to_resource(row: sqlite3.Row) -> Resource:
    return Resource(
        canonical_id=str(row["canonical_id"]),
        semantic_alias=str(row["semantic_alias"]),
        content_class=row["content_class"],
        mime=str(row["mime"]),
        byte_size=int(row["byte_size"]),
        token_count=(int(row["token_count"]) if row["token_count"] is not None else None),
        created_at=str(row["created_at"]),
        expires_at=str(row["expires_at"]),
    )


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("Resource clock must return a timezone-aware datetime")
    return value.astimezone(timezone.utc)
