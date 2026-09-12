from __future__ import annotations

import ast
from pathlib import Path


REPO_ROOT = Path(__file__).parents[2]
SOURCE_ROOT = REPO_ROOT / "src" / "houbridge"

LEGACY_PATHS = (
    "history/checkpoint.py",
    "history/undo.py",
    "history/snapshot_storage.py",
    "history/snapshot_trie.py",
    "history/embedded.py",
    "history/recovery.py",
    "history/synthetic.py",
    "houdini/snapshot.py",
    "houdini/graph_diff.py",
    "houdini/identity.py",
    "houdini/hip_read.py",
    "houdini/hip_read_script.py",
    "db/schema/project_schema.py",
)

LEGACY_IMPORTS = {
    "houbridge.history.checkpoint",
    "houbridge.history.undo",
    "houbridge.history.snapshot_storage",
    "houbridge.history.snapshot_trie",
    "houbridge.history.embedded",
    "houbridge.history.recovery",
    "houbridge.history.synthetic",
    "houbridge.houdini.snapshot",
    "houbridge.houdini.graph_diff",
    "houbridge.houdini.identity",
    "houbridge.houdini.hip_read",
    "houbridge.houdini.hip_read_script",
    "houbridge.db.schema.project_schema",
}


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imported.add(node.module)
    return imported


def test_legacy_history_modules_are_physically_absent() -> None:
    present = [relative for relative in LEGACY_PATHS if (SOURCE_ROOT / relative).exists()]

    assert present == []


def test_production_code_does_not_import_legacy_history_modules() -> None:
    violations: dict[str, list[str]] = {}
    for path in SOURCE_ROOT.rglob("*.py"):
        matches = sorted(_imported_modules(path) & LEGACY_IMPORTS)
        if matches:
            violations[str(path.relative_to(REPO_ROOT))] = matches

    assert violations == {}
