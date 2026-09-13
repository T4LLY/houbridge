from __future__ import annotations

from houbridge.errors import BridgeError
from houbridge.temporary_workspace import TemporaryWorkspace

from .invocation_store import StreamName, TaskInvocationStore
from .workspace import stream_path


class TaskStreamCollector:
    """Append newly flushed Task transport bytes into authoritative tasks.db chunks."""

    def __init__(self, invocations: TaskInvocationStore) -> None:
        self._invocations = invocations

    def drain(self, task_id: str, workspace: TemporaryWorkspace, *, final: bool = False) -> None:
        for stream in ("stdout", "stderr"):
            self._drain_one(task_id, workspace, stream, final=final)

    def _drain_one(
        self,
        task_id: str,
        workspace: TemporaryWorkspace,
        stream: StreamName,
        *,
        final: bool,
    ) -> None:
        state = self._invocations.get(task_id)
        if state is None:
            raise BridgeError(
                "task_invocation_missing",
                f"Task {task_id} has no recoverable invocation state.",
            )
        offset = state.committed_bytes(stream)
        path = stream_path(workspace, stream)
        try:
            size = path.stat().st_size
        except FileNotFoundError:
            if offset == 0:
                return
            raise BridgeError(
                "task_stream_missing",
                f"Task {task_id} {stream} transport stream disappeared during recovery.",
            )
        if size < offset:
            raise BridgeError(
                "task_stream_truncated",
                f"Task {task_id} {stream} transport stream was truncated during recovery.",
            )
        if size == offset:
            return

        with path.open("rb") as source:
            source.seek(offset)
            payload = source.read()
        text, consumed = _decode_complete_utf8(payload, final=final)
        if consumed == 0:
            return
        committed_offset = self._invocations.append_transport_chunk(
            task_id,
            stream,
            expected_offset=offset,
            consumed_bytes=consumed,
            content=text,
        )
        if committed_offset != offset + consumed:
            self._drain_one(task_id, workspace, stream, final=final)


def _decode_complete_utf8(payload: bytes, *, final: bool) -> tuple[str, int]:
    if not payload:
        return "", 0
    try:
        return payload.decode("utf-8"), len(payload)
    except UnicodeDecodeError as exc:
        if final or exc.reason != "unexpected end of data" or exc.end != len(payload):
            raise BridgeError(
                "task_stream_encoding",
                "Task transport stream is not valid UTF-8.",
            ) from exc
        prefix = payload[: exc.start]
        if not prefix:
            return "", 0
        try:
            return prefix.decode("utf-8"), len(prefix)
        except UnicodeDecodeError as prefix_exc:
            raise BridgeError(
                "task_stream_encoding",
                "Task transport stream is not valid UTF-8.",
            ) from prefix_exc
