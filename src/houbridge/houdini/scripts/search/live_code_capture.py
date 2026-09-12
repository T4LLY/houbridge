from __future__ import annotations

import json
from pathlib import Path


def _type_matches(type_name, configured_names):
    exact = str(type_name).casefold()
    base = exact.split("::", 1)[0]
    allowed = {str(name).casefold() for name in configured_names}
    return exact in allowed or base in allowed


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
    return _unique_nodes([root, *root.allSubChildren()])


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
        expanded.extend(node.allNodes())
    return _unique_nodes(expanded)


def run(request_path: str) -> None:
    import hou

    request = json.loads(Path(request_path).read_text(encoding="utf-8"))
    extractors = request["extractors"]
    output_path = Path(request["output_path"])
    path_filter = request.get("path")
    recursive = bool(request.get("recursive", False))

    records = []
    for node in _scope_nodes(hou, path_filter, recursive):
        try:
            session_id = int(node.sessionId())
            type_name = str(node.type().name())
            node_path = str(node.path())
        except Exception:
            continue
        for extractor in extractors:
            if not _type_matches(type_name, extractor.get("node_type_names", ())):
                continue
            for parameter_name in extractor.get("parameter_names", ()):
                try:
                    parm = node.parm(str(parameter_name))
                except Exception:
                    parm = None
                if parm is None:
                    continue
                try:
                    source = str(parm.rawValue())
                except Exception:
                    continue
                if not source.strip():
                    continue
                records.append(
                    {
                        "session_id": session_id,
                        "path": node_path,
                        "node_type": type_name,
                        "slot_id": "%s:%s" % (
                            extractor.get("name", "code"),
                            parameter_name,
                        ),
                        "parameter_name": str(parameter_name),
                        "language": str(extractor.get("language", "")),
                        "source": source,
                    }
                )

    records.sort(key=lambda item: (item["session_id"], item["slot_id"]))
    output_path.write_text(
        json.dumps({"nodes": records}, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
