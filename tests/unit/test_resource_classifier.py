from __future__ import annotations

from dataclasses import dataclass

import pytest

from houbridge.resource.classifier import classify_content


@dataclass(frozen=True)
class _DetectedType:
    mime: str


def test_classifier_uses_filetype_signature_before_text_decoding(monkeypatch) -> None:
    import houbridge.resource.classifier as classifier

    monkeypatch.setattr(classifier.filetype, "guess", lambda _payload: _DetectedType("image/png"))

    result = classify_content(b"\x89PNG\r\n\x1a\n")

    assert result.content_class == "binary"
    assert result.mime == "image/png"
    assert result.decoded_text is None


def test_classifier_falls_back_to_octet_stream_for_unknown_non_utf8(monkeypatch) -> None:
    import houbridge.resource.classifier as classifier

    monkeypatch.setattr(classifier.filetype, "guess", lambda _payload: None)

    result = classify_content(b"\xff\xfe\xfa")

    assert result.content_class == "binary"
    assert result.mime == "application/octet-stream"
    assert result.decoded_text is None


@pytest.mark.parametrize("control", [0x00, 0x01, 0x08, 0x0B, 0x0C, 0x0E, 0x1F, 0x7F])
def test_classifier_rejects_disallowed_controls(monkeypatch, control: int) -> None:
    import houbridge.resource.classifier as classifier

    monkeypatch.setattr(classifier.filetype, "guess", lambda _payload: None)

    result = classify_content(f"before{chr(control)}after".encode("utf-8"))

    assert result.content_class == "binary"
    assert result.mime == "application/octet-stream"


def test_classifier_keeps_tab_lf_and_cr_as_text_controls(monkeypatch) -> None:
    import houbridge.resource.classifier as classifier

    monkeypatch.setattr(classifier.filetype, "guess", lambda _payload: None)

    result = classify_content(b"alpha\tbeta\ngamma\rdelta")

    assert result.content_class == "text"
    assert result.mime == "text/plain"
    assert result.decoded_text == "alpha\tbeta\ngamma\rdelta"


def test_classifier_recognizes_valid_json_after_utf8(monkeypatch) -> None:
    import houbridge.resource.classifier as classifier

    monkeypatch.setattr(classifier.filetype, "guess", lambda _payload: None)

    result = classify_content('{"name":"日本語"}'.encode("utf-8"))

    assert result.content_class == "json"
    assert result.mime == "application/json"
    assert result.decoded_text == '{"name":"日本語"}'


def test_classifier_uses_text_plain_for_remaining_utf8(monkeypatch) -> None:
    import houbridge.resource.classifier as classifier

    monkeypatch.setattr(classifier.filetype, "guess", lambda _payload: None)

    result = classify_content("plain text".encode("utf-8"))

    assert result.content_class == "text"
    assert result.mime == "text/plain"


def test_classifier_does_not_treat_non_finite_python_json_extensions_as_json(monkeypatch) -> None:
    import houbridge.resource.classifier as classifier

    monkeypatch.setattr(classifier.filetype, "guess", lambda _payload: None)

    result = classify_content(b"NaN")

    assert result.content_class == "text"
    assert result.mime == "text/plain"
