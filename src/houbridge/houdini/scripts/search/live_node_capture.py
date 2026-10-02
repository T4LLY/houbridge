"""Inspect current Houdini nodes by path scope without using a persistent index."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


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


def capture_nodes(hou, *, path_filter=None, recursive=False):
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
    return {"nodes": records}


def run(request_path: str) -> None:
    import hou

    request = json.loads(Path(request_path).read_text(encoding="utf-8"))
    output_path = Path(request["output_path"])
    payload = capture_nodes(
        hou,
        path_filter=request.get("path"),
        recursive=bool(request.get("recursive", False)),
    )
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )


def _parse_args(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--path",
        help="Inspect this exact Houdini node path or direct-child glob scope.",
    )
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="Include descendants of nodes selected by --path.",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = _parse_args(sys.argv[1:] if argv is None else argv)

    # Keep Houdini-only imports after argument parsing so local --help works in
    # the wrapper host Python without requiring hou or a live Houdini Session.
    import hou

    return capture_nodes(
        hou,
        path_filter=args.path,
        recursive=args.recursive,
    )


if __name__ == "__main__":
    result = main()
