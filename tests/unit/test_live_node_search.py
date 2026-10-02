from __future__ import annotations

import fnmatch
import json
import runpy
import subprocess
import sys
from pathlib import Path

import pytest

from houbridge.errors import BridgeError
from houbridge.houdini.scripts.search import live_node_capture
from houbridge.live_node_search import LiveNodeEntry, LiveNodeSearchService


class _Category:
    def __init__(self, name: str) -> None:
        self._name = name

    def name(self) -> str:
        return self._name


class _Type:
    def __init__(self, name: str, category: str) -> None:
        self._name = name
        self._category = _Category(category)

    def name(self) -> str:
        return self._name

    def category(self) -> _Category:
        return self._category


class _Node:
    def __init__(self, session_id: int, path: str, type_name: str, category: str) -> None:
        self._session_id = session_id
        self._path = path
        self._name = "/" if path == "/" else path.rsplit("/", 1)[-1]
        self._type = _Type(type_name, category)
        self.children: list[_Node] = []

    def sessionId(self) -> int:
        return self._session_id

    def path(self) -> str:
        return self._path

    def name(self) -> str:
        return self._name

    def type(self) -> _Type:
        return self._type

    def allSubChildren(self):
        values = []
        for child in self.children:
            values.append(child)
            values.extend(child.allSubChildren())
        return tuple(values)

    def glob(self, pattern: str):
        return tuple(
            child
            for child in self.children
            if fnmatch.fnmatchcase(child.name(), pattern)
        )


class _Hou:
    def __init__(self, root: _Node) -> None:
        self._nodes = {node.path(): node for node in [root, *root.allSubChildren()]}

    def node(self, path: str):
        return self._nodes.get(path)


def _scene() -> _Node:
    root = _Node(1, "/", "root", "Manager")
    obj = _Node(2, "/obj", "obj", "Manager")
    geo = _Node(3, "/obj/geo1", "geo", "Object")
    box = _Node(4, "/obj/geo1/box1", "box", "Sop")
    wrangle = _Node(5, "/obj/geo1/attribwrangle1", "attribwrangle", "Sop")
    box_container = _Node(6, "/obj/box_container", "subnet", "Object")
    null = _Node(7, "/obj/box_container/null1", "null", "Sop")
    root.children = [obj]
    obj.children = [geo, box_container]
    geo.children = [box, wrangle]
    box_container.children = [null]
    return root


def _capture(tmp_path: Path, monkeypatch, *, path=None, recursive=False):
    root = _scene()
    monkeypatch.setitem(sys.modules, "hou", _Hou(root))
    output = tmp_path / "result.json"
    request = tmp_path / "request.json"
    request.write_text(
        json.dumps(
            {
                "output_path": str(output),
                "path": path,
                "recursive": recursive,
            }
        ),
        encoding="utf-8",
    )
    live_node_capture.run(str(request))
    return json.loads(output.read_text(encoding="utf-8"))["nodes"]


def test_physical_capture_scans_current_scene_without_persistent_index(
    tmp_path: Path,
    monkeypatch,
) -> None:
    nodes = _capture(tmp_path, monkeypatch)

    assert [item["path"] for item in nodes] == [
        "/obj",
        "/obj/geo1",
        "/obj/geo1/box1",
        "/obj/geo1/attribwrangle1",
        "/obj/box_container",
        "/obj/box_container/null1",
    ]
    assert set(nodes[1]) == {"path", "name", "type", "category"}


def test_physical_capture_supports_exact_scope_without_implicit_descendants(
    tmp_path: Path,
    monkeypatch,
) -> None:
    nodes = _capture(tmp_path, monkeypatch, path="/obj/geo1")

    assert [item["path"] for item in nodes] == ["/obj/geo1"]


def test_physical_capture_supports_direct_child_glob_and_recursive_descendants(
    tmp_path: Path,
    monkeypatch,
) -> None:
    direct = _capture(tmp_path, monkeypatch, path="/obj/geo*")
    recursive = _capture(tmp_path, monkeypatch, path="/obj/geo*", recursive=True)

    assert [item["path"] for item in direct] == ["/obj/geo1"]
    assert [item["path"] for item in recursive] == [
        "/obj/geo1",
        "/obj/geo1/box1",
        "/obj/geo1/attribwrangle1",
    ]


def test_capture_script_cli_mode_returns_declared_result(monkeypatch) -> None:
    root = _scene()
    monkeypatch.setitem(sys.modules, "hou", _Hou(root))
    monkeypatch.setattr(
        sys,
        "argv",
        [str(live_node_capture.__file__), "--path", "/obj/geo1", "--recursive"],
    )

    namespace = runpy.run_path(str(live_node_capture.__file__), run_name="__main__")

    assert [item["path"] for item in namespace["result"]["nodes"]] == [
        "/obj/geo1",
        "/obj/geo1/box1",
        "/obj/geo1/attribwrangle1",
    ]


def test_capture_script_help_does_not_require_houdini() -> None:
    completed = subprocess.run(
        [sys.executable, str(live_node_capture.__file__), "--help"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    assert completed.returncode == 0
    assert "Inspect current Houdini nodes" in completed.stdout
    assert "--path" in completed.stdout
    assert "--recursive" in completed.stdout


class _Resolver:
    def __init__(self) -> None:
        self.calls: list[int | None] = []
        self.resolved = object()

    def resolve(self, session=None):
        self.calls.append(session)
        return self.resolved


class _Capture:
    def __init__(self, entries: list[LiveNodeEntry]) -> None:
        self.entries = entries
        self.calls = []

    def capture(self, session, *, path=None, recursive=False):
        self.calls.append((session, path, recursive))
        return list(self.entries)


def _entry(path: str, name: str, type_name: str, category: str) -> LiveNodeEntry:
    return LiveNodeEntry(path=path, name=name, type=type_name, category=category)


def test_service_ranks_exact_prefix_substring_then_casefolded_path() -> None:
    entries = [
        _entry("/obj/z_exact", "target", "geo", "Object"),
        _entry("/obj/a_exact", "other", "TARGET", "Object"),
        _entry("/obj/prefix", "targetThing", "geo", "Object"),
        _entry("/obj/substring", "my_target_node", "geo", "Object"),
        _entry("/obj/unmatched", "other", "geo", "Object"),
    ]
    resolver = _Resolver()
    capture = _Capture(entries)
    service = LiveNodeSearchService(resolver, capture)

    result = service.search(
        "TaRgEt",
        top_k=4,
        path="/obj/*",
        recursive=True,
        session=3,
    )

    assert resolver.calls == [3]
    assert capture.calls == [(resolver.resolved, "/obj/*", True)]
    assert [hit["path"] for hit in result["hits"]] == [
        "/obj/a_exact",
        "/obj/z_exact",
        "/obj/prefix",
        "/obj/substring",
    ]
    assert all(set(hit) == {"path", "name", "type", "category"} for hit in result["hits"])
    assert all("score" not in hit for hit in result["hits"])


def test_service_does_not_match_ancestor_path_text() -> None:
    service = LiveNodeSearchService(
        _Resolver(),
        _Capture([_entry("/obj/box_container/null1", "null1", "null", "Sop")]),
    )

    assert service.search("box_container") == {"hits": []}


def test_service_applies_top_k_after_deterministic_ranking() -> None:
    service = LiveNodeSearchService(
        _Resolver(),
        _Capture(
            [
                _entry("/obj/c", "geo-c", "geo", "Object"),
                _entry("/obj/a", "geo-a", "geo", "Object"),
                _entry("/obj/b", "geo-b", "geo", "Object"),
            ]
        ),
    )

    assert [hit["path"] for hit in service.search("geo", top_k=2)["hits"]] == [
        "/obj/a",
        "/obj/b",
    ]


@pytest.mark.parametrize("query", ["", "   "])
def test_empty_query_is_rejected_before_session_resolution(query: str) -> None:
    resolver = _Resolver()
    service = LiveNodeSearchService(resolver, _Capture([]))

    with pytest.raises(BridgeError) as caught:
        service.search(query)

    assert caught.value.code == "empty_query"
    assert resolver.calls == []


def test_service_rejects_out_of_contract_top_k_before_session_resolution() -> None:
    resolver = _Resolver()
    service = LiveNodeSearchService(resolver, _Capture([]))

    with pytest.raises(BridgeError) as caught:
        service.search("geo", top_k=101)

    assert caught.value.code == "invalid_top_k"
    assert resolver.calls == []
