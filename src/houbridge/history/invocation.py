from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from houbridge.errors import BridgeError
from houbridge.process_coordination import ProcessIdentity
from houbridge.resource.store import ResourceStore
from houbridge.temporary_workspace import TemporaryWorkspace

from .changes import ActionChange, materialize_action_changes
from .service import HistorySessionStorage, HistoryStorageService


ResourceStoreFactory = Callable[[], ResourceStore]


@dataclass(frozen=True, slots=True)
class HistoryInvocationPreparation:
    runtime_script: Path
    request_path: Path
    capture_path: Path
    storage: HistorySessionStorage
    source_hash: str


class HistoryInvocationRecorder:
    """Common host-side History preflight/finalization for managed Python.

    Sync Execution and Async Task own their orchestration and terminal semantics.
    This service owns only History store/profile/source preparation, the Houdini
    recorder request, compact capture decoding, Action Change materialization,
    and final History persistence.
    """

    def __init__(
        self,
        storage: HistoryStorageService,
        *,
        resource_store_factory: ResourceStoreFactory,
        runtime_script: Path | None = None,
    ) -> None:
        self._storage = storage
        self._resource_store_factory = resource_store_factory
        if runtime_script is None:
            from houbridge.houdini.scripts.history import execution as history_runtime

            runtime_script = Path(history_runtime.__file__)
        self._runtime_script = runtime_script.resolve()

    def prepare(
        self,
        source: str,
        identity: ProcessIdentity,
        workspace: TemporaryWorkspace,
        *,
        requested_code_profile: str,
    ) -> HistoryInvocationPreparation:
        """Complete enabled History setup before caller Python may start."""

        try:
            storage = self._storage.for_recording(
                identity,
                enabled=True,
                requested_code_profile=requested_code_profile,
            )
            if storage is None:
                raise BridgeError(
                    "history_preflight_failed",
                    "Enabled History did not initialize recording storage.",
                )
            source_embedding = storage.store.embed_source(
                source,
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
        return HistoryInvocationPreparation(
            runtime_script=self._runtime_script,
            request_path=request_path,
            capture_path=capture_path,
            storage=storage,
            source_hash=source_embedding.source_hash,
        )

    def resume(
        self,
        identity: ProcessIdentity,
        workspace: TemporaryWorkspace,
        *,
        source_hash: str,
    ) -> HistoryInvocationPreparation:
        """Rebuild host finalization context without re-running preflight.

        Recovery is only used after a prior dispatch may already have started.
        Missing or invalid History state therefore becomes a finalization error,
        never a reason to replay caller Python.
        """

        storage = self._storage.existing_storage(identity)
        if storage is None:
            raise BridgeError(
                "history_finalize_failed",
                "History database is unavailable during execution finalization.",
            )
        request_path = workspace.path_for("history-request.json")
        capture_path = workspace.path_for("history-capture.json")
        return HistoryInvocationPreparation(
            runtime_script=self._runtime_script,
            request_path=request_path,
            capture_path=capture_path,
            storage=storage,
            source_hash=source_hash,
        )

    def finalize(
        self,
        preparation: HistoryInvocationPreparation,
        *,
        cwd: str,
        status: str,
        file: str,
        args: tuple[str, ...],
        purpose: str | None,
        execution_key: str | None = None,
    ) -> int | None:
        capture = _read_capture(preparation.capture_path)
        if capture["scene_replaced"]:
            return None
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

        return preparation.storage.store.commit_entry(
            expected_code_profile=preparation.storage.code_profile,
            time=str(capture["time"]),
            cwd=str(Path(cwd).resolve()),
            status=status,
            file=str(Path(file).resolve()),
            args=args,
            purpose=purpose,
            source_hash=preparation.source_hash,
            changes=changes,
            execution_key=execution_key,
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
