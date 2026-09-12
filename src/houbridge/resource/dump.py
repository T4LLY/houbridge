from __future__ import annotations

import mimetypes
import time
from dataclasses import dataclass, field
from typing import Callable

from houbridge.errors import BridgeError
from houbridge.resource.store import ResourceStore
from houbridge.temporary_artifact import TemporaryArtifactService


_RESOURCE_ARTIFACT_NAMESPACE = "resource"
_RESOURCE_ARTIFACT_STEM = "resource"


@dataclass(slots=True)
class ResourceDumper:
    store: ResourceStore
    artifacts: TemporaryArtifactService
    ttl_hours: int
    now_timestamp: Callable[[], float] = field(default=time.time, repr=False)

    def __post_init__(self) -> None:
        if self.ttl_hours < 1:
            raise ValueError("ttl_hours must be >= 1")

    def dump(self, resource_id: str) -> dict[str, object]:
        if not isinstance(resource_id, str) or not resource_id:
            raise BridgeError("invalid_resource_id", "Resource id must not be empty.")
        snapshot = self.store.get_payload(resource_id)
        if snapshot is None:
            raise BridgeError("resource_not_found", f"Resource not found: {resource_id}")
        resource, payload = snapshot
        extension = mimetypes.guess_extension(resource.mime) or ".bin"
        cutoff = float(self.now_timestamp()) - (self.ttl_hours * 60 * 60)

        try:
            self.artifacts.cleanup_before(
                namespace=_RESOURCE_ARTIFACT_NAMESPACE,
                cutoff_timestamp=cutoff,
            )
            path = self.artifacts.publish_bytes(
                payload,
                namespace=_RESOURCE_ARTIFACT_NAMESPACE,
                stem=_RESOURCE_ARTIFACT_STEM,
                extension=extension,
            )
        except (OSError, ValueError) as exc:
            raise BridgeError(
                "resource_dump_failed",
                "Unable to publish Resource dump.",
                f"{type(exc).__name__}: {exc}",
            ) from exc
        return {"path": str(path)}
