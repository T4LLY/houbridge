from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
import time
from typing import Callable

from houbridge.errors import BridgeError
from houbridge.temporary_artifact import TemporaryArtifactService

from .models import ScreenshotKind


_CAPTURE_NAMESPACE = "capture"


@dataclass(slots=True)
class CaptureArtifactPublisher:
    artifacts: TemporaryArtifactService
    retention_hours: int
    now_timestamp: Callable[[], float] = field(default=time.time, repr=False)
    now_datetime: Callable[[], datetime] = field(default=datetime.now, repr=False)

    def __post_init__(self) -> None:
        if self.retention_hours < 1:
            raise ValueError("retention_hours must be >= 1")

    def cleanup_expired(self) -> None:
        cutoff = float(self.now_timestamp()) - self.retention_hours * 60 * 60
        self.artifacts.cleanup_before(
            namespace=_CAPTURE_NAMESPACE,
            cutoff_timestamp=cutoff,
        )

    def publish_png(
        self,
        source: Path,
        *,
        kind: ScreenshotKind,
        captured_at: datetime | None = None,
    ) -> Path:
        if kind not in {"viewport", "window"}:
            raise ValueError(f"Unsupported screenshot kind: {kind}")
        at = captured_at or self.now_datetime()
        prefix = f"{kind}{at:%Y%m%d-%H%M}-"
        for sequence in range(1, 1000):
            stem = f"{prefix}{sequence:03d}"
            try:
                return self.artifacts.publish_file_exact(
                    source,
                    namespace=_CAPTURE_NAMESPACE,
                    stem=stem,
                    extension=".png",
                )
            except FileExistsError:
                continue
            except (OSError, ValueError) as exc:
                raise BridgeError(
                    "screenshot_failed",
                    "Unable to publish completed screenshot PNG.",
                    f"{type(exc).__name__}: {exc}",
                ) from exc
        raise BridgeError(
            "screenshot_failed",
            f"No screenshot sequence number remains for {prefix}DDD.png.",
        )
