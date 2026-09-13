from __future__ import annotations

import ast
import hashlib
import tokenize
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ScriptDocument:
    relative_path: str
    public_path: str
    source: str
    content_hash: str
    description: str | None
    semantic_text: str
    semantic_hash: str

    @property
    def entry_id(self) -> str:
        identity = f"workspace-script\0{self.relative_path}"
        return f"script:{_sha256_text(identity)[:32]}"

    @property
    def lexical_text(self) -> str:
        return f"{self.public_path}\n{self.semantic_text}"


def scan_script_documents(python_root: Path) -> list[ScriptDocument]:
    if not python_root.exists():
        return []

    documents: list[ScriptDocument] = []
    for path in sorted(python_root.rglob("*.py")):
        if not path.is_file():
            continue
        document = read_script_document(path, python_root=python_root)
        if document is not None:
            documents.append(document)
    return documents


def read_script_document(path: Path, *, python_root: Path) -> ScriptDocument | None:
    try:
        with tokenize.open(path) as handle:
            source = handle.read()
    except (OSError, SyntaxError, UnicodeError):
        return None

    if not source.strip():
        return None

    relative_path = path.relative_to(python_root).as_posix()
    description = module_description(source)
    semantic_text = (
        f"{description}\n\n{source}" if description is not None else source
    )
    return ScriptDocument(
        relative_path=relative_path,
        public_path=f".houbridge/python/{relative_path}",
        source=source,
        content_hash=_sha256_text(source),
        description=description,
        semantic_text=semantic_text,
        semantic_hash=_sha256_text(semantic_text),
    )


def module_description(source: str) -> str | None:
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return None

    description = ast.get_docstring(tree, clean=True)
    if description is None:
        return None
    normalized = description.strip()
    return normalized or None


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
