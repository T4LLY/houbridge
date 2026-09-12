from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
import time
from typing import Callable

from houbridge.errors import BridgeError
from houbridge.temporary_artifact import TemporaryArtifactService

from .models import ScreenshotKind
from .sequence import CaptureSequenceAllocator


_CAPTURE_NAMESPACE = "capture"


@dataclass(slots=True)
class CaptureArtifactPublisher:
    artifacts: TemporaryArtifactService
    retention_hours: int
    now_timestamp: Callable[[], float] = field(default=time.time, repr=False)
    now_datetime: Callable[[], datetime] = field(default=datetime.now, repr=False)
    _sequences: CaptureSequenceAllocator = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if self.retention_hours < 1:
            raise ValueError("retention_hours must be >= 1")
        self._sequences = CaptureSequenceAllocator(
            self.artifacts.root,
            _CAPTURE_NAMESPACE,
        )

    def cleanup_expired(self) -> None:
        cutoff = float(self.now_timestamp()) - self.retention_hours * 60 * 60
        self.artifacts.cleanup_before(
            namespace=_CAPTURE_NAMESPACE,
            cutoff_timestamp=cutoff,
        )
        self._sequences.cleanup_before(cutoff)

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
        key = f"{kind}{at:%Y%m%d-%H%M}"
        return self._publish_sequenced(
            source,
            key=key,
            extension=".png",
            error_code="screenshot_failed",
            error_message="Unable to publish completed screenshot PNG.",
        )

    def publish_turntable_mp4(
        self,
        source: Path,
        *,
        captured_at: datetime | None = None,
    ) -> Path:
        at = captured_at or self.now_datetime()
        key = f"turntable{at:%Y%m%d-%H%M}"
        return self._publish_sequenced(
            source,
            key=key,
            extension=".mp4",
            error_code="turntable_failed",
            error_message="Unable to publish completed turntable MP4.",
        )

    def _publish_sequenced(
        self,
        source: Path,
        *,
        key: str,
        extension: str,
        error_code: str,
        error_message: str,
    ) -> Path:
        while True:
            try:
                sequence = self._sequences.reserve(key)
                return self.artifacts.publish_file_exact(
                    source,
                    namespace=_CAPTURE_NAMESPACE,
                    stem=f"{key}-{sequence:03d}",
                    extension=extension,
                )
            except FileExistsError:
                # Existing output may predate durable sequence state. Reserving the
                # next number preserves monotonicity without overwriting it.
                continue
            except (OSError, ValueError) as exc:
                raise BridgeError(
                    error_code,
                    error_message,
                    f"{type(exc).__name__}: {exc}",
                ) from exc
