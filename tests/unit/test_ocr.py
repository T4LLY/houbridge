from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import houbridge.capture.ocr as ocr_module
from houbridge.capture.ocr import ScreenshotOCRService
from houbridge.errors import BridgeError
from houbridge.output.json import serialize_public_json
from houbridge.output.policy import OutputPolicy
from houbridge.output.tokens import FallbackTokenEstimator


class _Engine:
    def __init__(self, result, *, noisy: bool = False) -> None:
        self.result = result
        self.noisy = noisy
        self.calls: list[tuple[str, dict[str, object]]] = []

    def __call__(self, image: str, **kwargs):
        if self.noisy:
            print("runtime stdout noise")
            print("runtime stderr noise", file=sys.stderr)
        self.calls.append((image, kwargs))
        return self.result


def _image(tmp_path: Path) -> Path:
    path = tmp_path / "capture.png"
    path.write_bytes(b"image")
    return path


def test_ocr_groups_duplicate_text_and_uses_compact_bbox(tmp_path: Path) -> None:
    image = _image(tmp_path)
    engine = _Engine(
        SimpleNamespace(
            boxes=[
                [[10.2, 20.4], [30.6, 20.1], [30.7, 40.8], [10.0, 40.9]],
                [[50.0, 60.0], [70.0, 60.0], [70.0, 80.0], [50.0, 80.0]],
                [[90.0, 100.0], [110.0, 100.0], [110.0, 120.0], [90.0, 120.0]],
            ],
            txts=[" File\r\nMenu ", "File", "   "],
            scores=[0.99, 0.95, 0.5],
        )
    )

    result = ScreenshotOCRService(engine=engine).recognize(image)

    assert result == {
        "ocr": {
            "File Menu": [{"score": 0.99, "bbox": [10, 20, 31, 41]}],
            "File": [{"score": 0.95, "bbox": [50, 60, 70, 80]}],
        }
    }
    assert engine.calls == [
        (str(image), {"use_det": True, "use_cls": False, "use_rec": True})
    ]


def test_ocr_retains_multiple_occurrences_of_same_normalized_text(tmp_path: Path) -> None:
    image = _image(tmp_path)
    engine = _Engine(
        SimpleNamespace(
            boxes=[
                [[0, 0], [10, 0], [10, 10], [0, 10]],
                [[20, 20], [30, 20], [30, 30], [20, 30]],
            ],
            txts=["File", "File"],
            scores=[0.9, None],
        )
    )

    assert ScreenshotOCRService(engine=engine).recognize(image) == {
        "ocr": {
            "File": [
                {"score": 0.9, "bbox": [0, 0, 10, 10]},
                {"score": None, "bbox": [20, 20, 30, 30]},
            ]
        }
    }


def test_ocr_returns_empty_mapping_when_engine_finds_no_boxes(tmp_path: Path) -> None:
    image = _image(tmp_path)
    engine = _Engine(SimpleNamespace(boxes=None, txts=None, scores=None))

    assert ScreenshotOCRService(engine=engine).recognize(image) == {"ocr": {}}


def test_ocr_rejects_missing_image_before_engine_initialization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    def build_engine():
        nonlocal called
        called = True
        return object()

    monkeypatch.setattr(ocr_module, "_build_engine", build_engine)

    with pytest.raises(BridgeError) as caught:
        ScreenshotOCRService().recognize(tmp_path / "missing.png")

    assert caught.value.code == "ocr_image_not_found"
    assert called is False


@pytest.mark.parametrize(
    "result",
    [
        SimpleNamespace(boxes=[[]], txts=["File"], scores=[0.9]),
        SimpleNamespace(boxes=[[[0, 0], [1, 1]]], txts=["File"], scores=["bad"]),
    ],
)
def test_ocr_rejects_malformed_engine_results(tmp_path: Path, result) -> None:
    image = _image(tmp_path)

    with pytest.raises(BridgeError) as caught:
        ScreenshotOCRService(engine=_Engine(result)).recognize(image)

    assert caught.value.code == "ocr_result_invalid"


def test_ocr_runtime_output_is_suppressed(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    image = _image(tmp_path)
    engine = _Engine(SimpleNamespace(boxes=None, txts=None, scores=None), noisy=True)

    ScreenshotOCRService(engine=engine).recognize(image)

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


@pytest.mark.parametrize(
    ("environment", "expected_suffix"),
    [
        ({"HF_ASSETS_CACHE": "assets", "HF_HOME": "home", "XDG_CACHE_HOME": "xdg"}, "assets"),
        ({"HF_HOME": "home", "XDG_CACHE_HOME": "xdg"}, "home/assets"),
        ({"XDG_CACHE_HOME": "xdg"}, "xdg/huggingface/assets"),
    ],
)
def test_huggingface_assets_cache_precedence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    environment: dict[str, str],
    expected_suffix: str,
) -> None:
    for name in ("HF_ASSETS_CACHE", "HF_HOME", "XDG_CACHE_HOME"):
        monkeypatch.delenv(name, raising=False)
    for name, relative in environment.items():
        monkeypatch.setenv(name, str(tmp_path / relative))

    expected = tmp_path / expected_suffix
    assert ocr_module._huggingface_assets_cache() == expected
    assert ocr_module._rapidocr_model_root() == expected / "houbridge" / "rapidocr"


def test_huggingface_assets_cache_uses_normal_user_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in ("HF_ASSETS_CACHE", "HF_HOME", "XDG_CACHE_HOME"):
        monkeypatch.delenv(name, raising=False)

    assert ocr_module._huggingface_assets_cache() == (
        Path.home() / ".cache" / "huggingface" / "assets"
    )


def test_build_engine_is_quiet_and_uses_defined_profile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    captured: dict[str, object] = {}

    class _RapidOCR:
        def __init__(self, *, params):
            print("initialization stdout noise")
            print("initialization stderr noise", file=sys.stderr)
            captured["params"] = params

    fake_module = SimpleNamespace(
        EngineType=SimpleNamespace(ONNXRUNTIME="onnxruntime"),
        ModelType=SimpleNamespace(TINY="tiny"),
        OCRVersion=SimpleNamespace(PPOCRV6="PP-OCRv6"),
        RapidOCR=_RapidOCR,
    )
    monkeypatch.setitem(sys.modules, "rapidocr", fake_module)
    monkeypatch.setenv("HF_ASSETS_CACHE", str(tmp_path / "hf-assets"))

    engine = ocr_module._build_engine()

    assert isinstance(engine, _RapidOCR)
    assert capsys.readouterr() == ("", "")
    assert captured["params"] == {
        "Global.log_level": "critical",
        "Global.model_root_dir": str(
            tmp_path / "hf-assets" / "houbridge" / "rapidocr"
        ),
        "Det.engine_type": "onnxruntime",
        "Det.model_type": "tiny",
        "Det.ocr_version": "PP-OCRv6",
        "Rec.engine_type": "onnxruntime",
        "Rec.model_type": "tiny",
        "Rec.ocr_version": "PP-OCRv6",
    }


def test_large_ocr_result_is_resource_backed_only_by_common_output_policy(tmp_path: Path) -> None:
    image = _image(tmp_path)
    texts = [f"label-{index}-" + ("x" * 40) for index in range(40)]
    engine = _Engine(
        SimpleNamespace(
            boxes=[[[0, 0], [10, 0], [10, 10], [0, 10]]] * len(texts),
            txts=texts,
            scores=[0.99] * len(texts),
        )
    )
    logical = ScreenshotOCRService(engine=engine).recognize(image)
    stored: list[bytes] = []

    class _Store:
        def put_bytes(self, payload: bytes):
            stored.append(payload)
            return SimpleNamespace(semantic_alias="ocr-output-000")

    policy = OutputPolicy(
        inline_max_tokens=1,
        token_estimator=FallbackTokenEstimator(),
        resource_store_factory=_Store,
    )

    assert list(logical) == ["ocr"]
    assert policy.render(logical) == '{"resource":"ocr-output-000"}'
    assert stored == [serialize_public_json(logical).encode("utf-8")]
