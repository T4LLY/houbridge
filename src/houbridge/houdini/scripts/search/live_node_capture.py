from __future__ import annotations

import json
from pathlib import Path


def _unique_nodes(nodes):
    unique = {}
    for node in nodes:
        try:
            session_id = int(node.sessionId())
        except Exception:
            continue
        unique.setdefault(session_id, node)
    return [unique[key] for key in sorted(unique)]


def _all_nodes(hou):
    root = hou.node("/")
    if root is None:
        raise RuntimeError("hou.node('/') returned None")
    return _unique_nodes(root.allSubChildren())


def _scope_nodes(hou, path_filter, recursive):
    if not path_filter:
        return _all_nodes(hou)

    exact = hou.node(path_filter)
    if exact is not None:
        selected = [exact]
    else:
        parent_path, separator, pattern = str(path_filter).rpartition("/")
        if not separator:
            parent_path = "/"
            pattern = str(path_filter)
        elif not parent_path:
            parent_path = "/"
        parent = hou.node(parent_path)
        if parent is None:
            return []
        selected = list(parent.glob(pattern))

    if not recursive:
        return _unique_nodes(selected)

    expanded = []
    for node in selected:
        expanded.append(node)
        expanded.extend(node.allSubChildren())
    return _unique_nodes(expanded)


def run(request_path: str) -> None:
    import hou

    request = json.loads(Path(request_path).read_text(encoding="utf-8"))
    output_path = Path(request["output_path"])
    path_filter = request.get("path")
    recursive = bool(request.get("recursive", False))

    records = []
    for node in _scope_nodes(hou, path_filter, recursive):
        try:
            node_type = node.type()
            records.append(
                {
                    "path": str(node.path()),
                    "name": str(node.name()),
                    "type": str(node_type.name()),
                    "category": str(node_type.category().name()),
                }
            )
        except Exception:
            continue

    output_path.write_text(
        json.dumps({"nodes": records}, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
