from __future__ import annotations

import io
import os
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any

from houbridge.errors import BridgeError


class ScreenshotOCRService:
    """Recognize text in an existing screenshot without owning output policy."""

    def __init__(self, engine: Any | None = None) -> None:
        self._engine = engine

    def recognize(self, image_path: Path) -> dict[str, object]:
        path = Path(image_path)
        if not path.is_file():
            raise BridgeError(
                "ocr_image_not_found",
                "OCR input image does not exist.",
                str(path),
            )

        engine = self._engine if self._engine is not None else _build_engine()
        try:
            with _quiet_ocr_runtime():
                result = engine(str(path), use_det=True, use_cls=False, use_rec=True)
        except BridgeError:
            raise
        except Exception as exc:
            raise BridgeError(
                "ocr_failed",
                "OCR failed while processing the image.",
                f"{type(exc).__name__}: {exc}",
            ) from exc

        return {"ocr": _format_recognition_result(result)}


def _format_recognition_result(result: Any) -> dict[str, list[dict[str, object]]]:
    if result is None or getattr(result, "boxes", None) is None:
        return {}

    boxes = result.boxes
    texts = getattr(result, "txts", None)
    scores = getattr(result, "scores", None)
    if texts is None:
        texts = ()
    if scores is None:
        scores = ()
    recognized: dict[str, list[dict[str, object]]] = {}

    for index, polygon in enumerate(boxes):
        text = _normalize_text(texts[index] if index < len(texts) else "")
        if not text:
            continue

        bbox = _compact_bbox(polygon, index=index)
        score = _score_at(scores, index=index)
        recognized.setdefault(text, []).append({"score": score, "bbox": bbox})

    return recognized


def _normalize_text(value: Any) -> str:
    return " ".join(str(value).splitlines()).strip()


def _compact_bbox(polygon: Any, *, index: int) -> list[int]:
    try:
        xs = [float(point[0]) for point in polygon]
        ys = [float(point[1]) for point in polygon]
    except (TypeError, ValueError, IndexError) as exc:
        raise _invalid_result_error(index, "invalid text bounding box") from exc

    if not xs or not ys:
        raise _invalid_result_error(index, "empty text bounding box")

    return [
        round(min(xs)),
        round(min(ys)),
        round(max(xs)),
        round(max(ys)),
    ]


def _score_at(scores: Any, *, index: int) -> float | None:
    if index >= len(scores) or scores[index] is None:
        return None
    try:
        return float(scores[index])
    except (TypeError, ValueError) as exc:
        raise _invalid_result_error(index, "invalid recognition score") from exc


def _invalid_result_error(index: int, reason: str) -> BridgeError:
    return BridgeError(
        "ocr_result_invalid",
        "OCR returned an invalid recognition result.",
        f"index={index}; reason={reason}",
    )


def _huggingface_assets_cache() -> Path:
    explicit = os.environ.get("HF_ASSETS_CACHE")
    if explicit:
        return Path(explicit).expanduser()

    hf_home = os.environ.get("HF_HOME")
    if hf_home:
        return Path(hf_home).expanduser() / "assets"

    xdg_cache_home = os.environ.get("XDG_CACHE_HOME")
    if xdg_cache_home:
        return Path(xdg_cache_home).expanduser() / "huggingface" / "assets"

    return Path.home() / ".cache" / "huggingface" / "assets"


def _rapidocr_model_root() -> Path:
    return _huggingface_assets_cache() / "houbridge" / "rapidocr"


def _build_engine() -> Any:
    try:
        from rapidocr import EngineType, ModelType, OCRVersion, RapidOCR
    except ImportError as exc:
        raise BridgeError(
            "ocr_dependency_unavailable",
            "OCR runtime dependencies are not installed.",
            f"{type(exc).__name__}: {exc}",
        ) from exc

    try:
        with _quiet_ocr_runtime():
            return RapidOCR(
                params={
                    "Global.log_level": "critical",
                    "Global.model_root_dir": str(_rapidocr_model_root()),
                    "Det.engine_type": EngineType.ONNXRUNTIME,
                    "Det.model_type": ModelType.TINY,
                    "Det.ocr_version": OCRVersion.PPOCRV6,
                    "Rec.engine_type": EngineType.ONNXRUNTIME,
                    "Rec.model_type": ModelType.TINY,
                    "Rec.ocr_version": OCRVersion.PPOCRV6,
                }
            )
    except BridgeError:
        raise
    except Exception as exc:
        raise BridgeError(
            "ocr_engine_init_failed",
            "OCR engine initialization failed.",
            f"{type(exc).__name__}: {exc}",
        ) from exc


@contextmanager
def _quiet_ocr_runtime():
    """Keep third-party OCR progress/noise away from machine-readable output."""

    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        yield
