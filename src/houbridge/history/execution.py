from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from houbridge.errors import BridgeError
from houbridge.execution.history import ExecutionHistoryPreparation
from houbridge.execution.models import ExecutionInvocation, ExecutionOutcome
from houbridge.resource.store import ResourceStore
from houbridge.session.resolver import ResolvedSession
from houbridge.temporary_workspace import TemporaryWorkspace

from .changes import ActionChange, materialize_action_changes
from .service import HistorySessionStorage, HistoryStorageService


ResourceStoreFactory = Callable[[], ResourceStore]


@dataclass(frozen=True, slots=True)
class SynchronousHistoryPreparation:
    runtime_script: Path
    request_path: Path
    capture_path: Path
    storage: HistorySessionStorage
    source_hash: str


class SynchronousExecutionHistory:
    """History implementation of the synchronous Execution history boundary."""

    def __init__(
        self,
        storage: HistoryStorageService,
        *,
        requested_code_profile: str,
        resource_store_factory: ResourceStoreFactory,
        runtime_script: Path | None = None,
    ) -> None:
        self._storage = storage
        self._requested_code_profile = requested_code_profile
        self._resource_store_factory = resource_store_factory
        if runtime_script is None:
            from houbridge.houdini.scripts.history import execution as history_runtime

            runtime_script = Path(history_runtime.__file__)
        self._runtime_script = runtime_script.resolve()

    def prepare(
        self,
        invocation: ExecutionInvocation,
        session: ResolvedSession,
        workspace: TemporaryWorkspace,
    ) -> SynchronousHistoryPreparation:
        """Complete store/profile/source preflight before Houdini may run caller Python."""

        try:
            storage = self._storage.for_recording(
                session.identity,
                enabled=True,
                requested_code_profile=self._requested_code_profile,
            )
            if storage is None:
                raise BridgeError(
                    "history_preflight_failed",
                    "Enabled History did not initialize recording storage.",
                )
            source_embedding = storage.store.embed_source(
                invocation.source,
                requested_code_profile=storage.code_profile,
            )
        except BridgeError:
            raise
        except Exception as exc:
            raise BridgeError(
                "history_preflight_failed",
                "History store/profile/source embedding preflight failed.",
                f"{type(exc).__name__}: {exc}",
            ) from exc
        request_path = workspace.path_for("history-request.json")
        capture_path = workspace.path_for("history-capture.json")
        request_path.write_text(
            json.dumps(
                {
                    "database_path": str(storage.store.database.resolve()),
                    "capture_file": str(capture_path.resolve()),
                },
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            encoding="utf-8",
            newline="\n",
        )
        return SynchronousHistoryPreparation(
            runtime_script=self._runtime_script,
            request_path=request_path,
            capture_path=capture_path,
            storage=storage,
            source_hash=source_embedding.source_hash,
        )

    def finalize(
        self,
        preparation: ExecutionHistoryPreparation,
        invocation: ExecutionInvocation,
        session: ResolvedSession,
        outcome: ExecutionOutcome,
        workspace: TemporaryWorkspace,
    ) -> None:
        if not isinstance(preparation, SynchronousHistoryPreparation):
            raise BridgeError(
                "history_finalize_failed",
                "History preparation does not belong to synchronous History.",
            )
        if preparation.storage.identity != session.identity:
            raise BridgeError(
                "history_finalize_failed",
                "History preparation target changed before finalization.",
            )

        capture = _read_capture(preparation.capture_path)
        if capture["scene_replaced"]:
            return
        raw_changes = capture["changes"]
        assert isinstance(raw_changes, list)
        changes: tuple[ActionChange, ...]
        if raw_changes:
            changes = materialize_action_changes(
                raw_changes,
                resources=self._resource_store_factory(),
            )
        else:
            changes = ()

        preparation.storage.store.commit_entry(
            expected_code_profile=preparation.storage.code_profile,
            time=str(capture["time"]),
            cwd=_normalized_absolute_cwd(invocation.origin_cwd),
            status="completed" if outcome.python_ok else "failed",
            file=_normalized_absolute_file(invocation),
            args=invocation.argv[1:],
            purpose=invocation.purpose,
            source_hash=preparation.source_hash,
            changes=changes,
        )


def _read_capture(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise BridgeError(
            "history_finalize_failed",
            "History capture did not publish a valid finalization payload.",
            f"{type(exc).__name__}: {exc}",
        ) from exc
    if not isinstance(payload, dict) or set(payload) != {"time", "scene_replaced", "changes"}:
        raise BridgeError(
            "history_finalize_failed",
            "History capture finalization payload has an invalid shape.",
        )
    timestamp = payload["time"]
    scene_replaced = payload["scene_replaced"]
    changes = payload["changes"]
    if not isinstance(timestamp, str) or not timestamp:
        raise BridgeError("history_finalize_failed", "History capture time is invalid.")
    try:
        datetime.fromisoformat(timestamp)
    except ValueError as exc:
        raise BridgeError("history_finalize_failed", "History capture time is invalid.") from exc
    if not isinstance(scene_replaced, bool) or not isinstance(changes, list):
        raise BridgeError(
            "history_finalize_failed",
            "History capture finalization payload has invalid values.",
        )
    if scene_replaced and changes:
        raise BridgeError(
            "history_finalize_failed",
            "Scene-replaced History capture must not contain Action Changes.",
        )
    return payload


def _normalized_absolute_cwd(value: str) -> str:
    return str(Path(value).resolve())


def _normalized_absolute_file(invocation: ExecutionInvocation) -> str:
    path = Path(invocation.source_path)
    if not path.is_absolute():
        path = Path(invocation.origin_cwd) / path
    return str(path.resolve())
