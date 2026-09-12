from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from houbridge.paths import GlobalDataPaths
from houbridge.process_coordination import ProcessIdentity
from houbridge.search.embedding import EmbeddingProvider

from .identity import history_session_key
from .store import HistoryStore


@dataclass(frozen=True, slots=True)
class HistorySessionStorage:
    identity: ProcessIdentity
    session_key: str
    store: HistoryStore
    code_profile: str


class HistoryStorageService:
    """Resolve exact-process History storage without owning Execution state."""

    def __init__(
        self,
        paths: GlobalDataPaths,
        *,
        embedding_provider: EmbeddingProvider | None = None,
    ) -> None:
        self._paths = paths
        self._embedding_provider = embedding_provider

    def database_for(self, identity: ProcessIdentity) -> Path:
        key = history_session_key(identity)
        return self._paths.history_session(key).database

    def for_recording(
        self,
        identity: ProcessIdentity,
        *,
        enabled: bool,
        requested_code_profile: str,
    ) -> HistorySessionStorage | None:
        # Disabled History must not initialize a database or an embedding model.
        if not enabled:
            return None
        key = history_session_key(identity)
        store = HistoryStore(
            self._paths.history_session(key).database,
            embedding_provider=self._embedding_provider,
        )
        profile = store.initialize(requested_code_profile)
        return HistorySessionStorage(
            identity=identity,
            session_key=key,
            store=store,
            code_profile=profile,
        )

    def existing(self, identity: ProcessIdentity) -> HistoryStore | None:
        database = self.database_for(identity)
        if not database.is_file():
            return None
        return HistoryStore(database, embedding_provider=self._embedding_provider)
