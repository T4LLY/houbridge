from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

import houbridge.semantic_id as semantic_id
from houbridge.errors import BridgeError
from houbridge.semantic_id import PotionSemanticBaseGenerator, normalized_token_text, token_quality


def test_normalized_token_text_removes_tokenizer_prefixes() -> None:
    assert normalized_token_text("▁ĠGraph") == ("Graph", False)
    assert normalized_token_text("##node") == ("node", True)


@pytest.mark.parametrize(
    "token",
    ["", "##node", "123", "0xdead", "café", "_", "\x01node", "a1f"],
)
def test_token_quality_rejects_unusable_atoms(token: str) -> None:
    assert token_quality(token) is False


@pytest.mark.parametrize("token", ["node", "graph_2", "python", "shader pass"])
def test_token_quality_accepts_readable_atoms(token: str) -> None:
    assert token_quality(token) is True


def test_generator_selects_three_distinct_tags_from_representative_alias_group(
    monkeypatch,
) -> None:
    model = SimpleNamespace(
        tokens=["node", "node", "graph", "python", "123"],
        encode=lambda _text, max_length=None: np.asarray([1.0, 0.0]),
    )
    vectors = semantic_id._unit_rows(
        np.asarray(
            [
                [1.0, 0.0],
                [0.99, 0.01],
                [0.95, 0.05],
                [0.90, 0.10],
                [0.0, 1.0],
            ]
        )
    )
    state = semantic_id._PotionState(
        model=model,
        normalized_vocab=vectors,
        quality_mask=np.asarray([True, True, True, True, False]),
    )
    monkeypatch.setattr(semantic_id, "_load_potion_state", lambda _model_id: state)

    base = PotionSemanticBaseGenerator().generate(
        "node graph python",
        fallback_stem="caller-fallback",
    )

    assert base.prefix == "node-graph-python"
    assert base.tags == ("node", "graph", "python")
    assert base.used_fallback is False


def test_generator_uses_caller_fallback_only_for_zero_embedding(monkeypatch) -> None:
    model = SimpleNamespace(
        tokens=["node", "graph", "python"],
        encode=lambda _text, max_length=None: np.asarray([0.0, 0.0]),
    )
    state = semantic_id._PotionState(
        model=model,
        normalized_vocab=np.eye(3, 2),
        quality_mask=np.asarray([True, True, True]),
    )
    monkeypatch.setattr(semantic_id, "_load_potion_state", lambda _model_id: state)

    base = PotionSemanticBaseGenerator().generate(
        "anything",
        fallback_stem="task-unknown",
    )

    assert base.prefix == "task-unknown"
    assert base.tags == ()
    assert base.used_fallback is True


def test_generator_does_not_hide_insufficient_alias_tags_with_fallback(monkeypatch) -> None:
    model = SimpleNamespace(
        tokens=["node", "graph", "python"],
        encode=lambda _text, max_length=None: np.asarray([1.0, 0.0]),
    )
    state = semantic_id._PotionState(
        model=model,
        normalized_vocab=np.asarray([[1.0, 0.0], [0.0, 1.0], [-1.0, 0.0]]),
        quality_mask=np.asarray([True, True, True]),
    )
    monkeypatch.setattr(semantic_id, "_load_potion_state", lambda _model_id: state)

    with pytest.raises(BridgeError) as exc_info:
        PotionSemanticBaseGenerator(alias_threshold=0.9).generate(
            "anything",
            fallback_stem="resource-unknown-content",
        )

    assert exc_info.value.code == "semantic_id_generation_failed"
