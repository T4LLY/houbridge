from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import numpy as np

from houbridge.errors import BridgeError


MODEL_ID = "minishlab/potion-code-16M-v2"
DEFAULT_ALIAS_THRESHOLD = 0.35
DEFAULT_TAG_COUNT = 3
EPS = 1e-12

_TOKENIZER_PREFIXES = ("##", "▁", "Ġ")
_NUMERIC_LITERAL_RE = re.compile(
    r"^[+-]?(?:0x[0-9a-f]+|0b[01]+|0o[0-7]+|"
    r"(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?)$",
    re.IGNORECASE,
)
_HEXISH_RE = re.compile(r"^[0-9a-f]+$", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class SemanticBase:
    """Feature-neutral semantic prefix returned before ordinal allocation."""

    prefix: str
    tags: tuple[str, ...]
    used_fallback: bool = False


@dataclass(frozen=True, slots=True)
class _PotionState:
    model: Any
    normalized_vocab: np.ndarray
    quality_mask: np.ndarray


def normalized_token_text(token: str) -> tuple[str, bool]:
    value = token.strip()
    continuation = value.startswith("##")
    changed = True
    while changed and value:
        changed = False
        for prefix in _TOKENIZER_PREFIXES:
            if value.startswith(prefix):
                value = value[len(prefix) :]
                changed = True
    return value.strip(), continuation


def token_quality(token: str) -> bool:
    value, continuation = normalized_token_text(token)
    if not value or continuation or len(value) < 2 or len(value) > 96:
        return False
    if _NUMERIC_LITERAL_RE.fullmatch(value):
        return False
    if any(ord(char) > 127 or ord(char) < 32 for char in value):
        return False
    if not any("a" <= char.lower() <= "z" for char in value):
        return False
    lower = value.lower()
    if _HEXISH_RE.fullmatch(lower) and any(char.isdigit() for char in lower):
        return False
    return True


def _id_tag(token: str) -> str:
    value, continuation = normalized_token_text(token)
    if continuation:
        return ""
    value = "_".join(value.strip().lower().split())
    return "".join(
        char
        for char in value
        if ("a" <= char <= "z") or ("0" <= char <= "9") or char == "_"
    )


def _unit_rows(matrix: np.ndarray) -> np.ndarray:
    array = np.asarray(matrix, dtype=np.float64)
    norms = np.linalg.norm(array, axis=1, keepdims=True)
    return array / np.maximum(norms, EPS)


def _unit_vector_or_fallback(vector: np.ndarray) -> np.ndarray | None:
    array = np.asarray(vector, dtype=np.float64).reshape(-1)
    if array.size == 0:
        return None
    norm = float(np.linalg.norm(array))
    if not np.isfinite(norm):
        raise BridgeError(
            "semantic_id_generation_failed",
            "Potion produced a non-finite semantic embedding.",
        )
    if norm <= EPS:
        return None
    return array / norm


def _effective_token_vectors(model: Any) -> np.ndarray:
    if model.token_mapping is None:
        vectors = np.asarray(model.embedding, dtype=np.float32)
    else:
        vectors = np.asarray(model.embedding[model.token_mapping], dtype=np.float32)
    if model.weights is not None:
        vectors = vectors * np.asarray(model.weights, dtype=np.float32)[:, None]
    return vectors


@lru_cache(maxsize=2)
def _load_potion_state(model_id: str) -> _PotionState:
    try:
        from huggingface_hub.utils import disable_progress_bars
        from model2vec import StaticModel

        with disable_progress_bars():
            model = StaticModel.from_pretrained(model_id)
    except Exception as exc:
        raise BridgeError(
            "semantic_id_model_load_failed",
            f"Unable to load semantic ID model: {model_id}",
            detail=str(exc),
        ) from exc

    vectors = _unit_rows(_effective_token_vectors(model))
    quality_mask = np.asarray(
        [token_quality(str(token)) for token in model.tokens],
        dtype=bool,
    )
    if model.unk_token_id is not None:
        quality_mask[int(model.unk_token_id)] = False
    if vectors.shape[0] != len(model.tokens):
        raise BridgeError(
            "semantic_id_model_invalid",
            "Potion native vocabulary/vector count mismatch.",
        )
    return _PotionState(model, vectors, quality_mask)


class PotionSemanticBaseGenerator:
    """Generate a feature-neutral three-tag semantic prefix with Potion."""

    def __init__(
        self,
        *,
        model_id: str = MODEL_ID,
        alias_threshold: float = DEFAULT_ALIAS_THRESHOLD,
        tag_count: int = DEFAULT_TAG_COUNT,
    ) -> None:
        if not 0.0 < alias_threshold <= 1.0:
            raise ValueError("alias_threshold must be in (0, 1]")
        if tag_count < 1:
            raise ValueError("tag_count must be >= 1")
        self.model_id = model_id
        self.alias_threshold = alias_threshold
        self.tag_count = tag_count

    def generate(self, text: str, *, fallback_stem: str) -> SemanticBase:
        if not fallback_stem.strip():
            raise ValueError("fallback_stem must not be empty")
        if not text.strip():
            raise BridgeError(
                "semantic_id_generation_failed",
                "Semantic text must not be empty.",
            )

        try:
            vector = self._state.model.encode(text, max_length=None)
        except Exception as exc:
            raise BridgeError(
                "semantic_id_generation_failed",
                "Unable to embed content for semantic ID generation.",
                detail=str(exc),
            ) from exc

        query = _unit_vector_or_fallback(np.asarray(vector, dtype=np.float64))
        if query is None:
            return SemanticBase(prefix=fallback_stem, tags=(), used_fallback=True)

        ranking = self._state.normalized_vocab @ query
        active = self._state.quality_mask & np.isfinite(ranking)
        if not np.any(active):
            raise BridgeError(
                "semantic_id_generation_failed",
                "No usable Potion vocabulary atom matched the semantic content.",
            )

        representative_id = int(np.argmax(np.where(active, ranking, -np.inf)))
        representative_similarity = (
            self._state.normalized_vocab @ self._state.normalized_vocab[representative_id]
        )
        alias_ids = np.flatnonzero(
            active & (representative_similarity >= self.alias_threshold)
        )
        alias_order = alias_ids[
            np.argsort(-ranking[alias_ids], kind="stable")
        ]

        selected: list[str] = []
        seen: set[str] = set()
        for token_id in alias_order:
            tag = _id_tag(str(self._state.model.tokens[int(token_id)]))
            if not tag:
                continue
            key = tag.casefold()
            if key in seen:
                continue
            seen.add(key)
            selected.append(tag)
            if len(selected) == self.tag_count:
                break

        if len(selected) < self.tag_count:
            raise BridgeError(
                "semantic_id_generation_failed",
                (
                    "Semantic alias group does not contain three distinct usable tags "
                    f"at cosine >= {self.alias_threshold}."
                ),
            )

        tags = tuple(selected)
        return SemanticBase(prefix="-".join(tags), tags=tags)

    @property
    def _state(self) -> _PotionState:
        return _load_potion_state(self.model_id)
