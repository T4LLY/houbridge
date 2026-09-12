from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Sequence


@dataclass(frozen=True, slots=True)
class CodeExtractorSpec:
    name: str
    language: str
    node_type_names: tuple[str, ...]
    parameter_names: tuple[str, ...]

    def to_payload(self) -> dict[str, object]:
        return {
            "name": self.name,
            "language": self.language,
            "node_type_names": list(self.node_type_names),
            "parameter_names": list(self.parameter_names),
        }


BUILTIN_CODE_EXTRACTORS: tuple[CodeExtractorSpec, ...] = (
    CodeExtractorSpec(
        name="vex-wrangle",
        language="vex",
        node_type_names=(
            "attribwrangle",
            "pointwrangle",
            "primitivewrangle",
            "vertexwrangle",
            "volumewrangle",
            "wrangle",
        ),
        parameter_names=("snippet",),
    ),
    CodeExtractorSpec(
        name="python-node",
        language="python",
        node_type_names=("python", "pythonscript"),
        parameter_names=("python", "code", "script"),
    ),
)


def extractor_registry_payload(
    specs: Sequence[CodeExtractorSpec] = BUILTIN_CODE_EXTRACTORS,
) -> list[dict[str, object]]:
    return [spec.to_payload() for spec in specs]
