from __future__ import annotations

import fnmatch
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from houbridge.errors import BridgeError
from houbridge.houdini.scripts.search import live_code_capture
from houbridge.live_code_search.extractors import BUILTIN_CODE_EXTRACTORS
from houbridge.live_code_search.models import LiveCodeEntry, RankedLiveCode
from houbridge.live_code_search.service import LiveCodeSearchService


class _Parm:
    def __init__(self, value: str) -> None:
        self.value = value
        self.raw_calls = 0

    def rawValue(self) -> str:
        self.raw_calls += 1
        return self.value


class _Type:
    def __init__(self, name: str) -> None:
        self._name = name

    def name(self) -> str:
        return self._name


class _Node:
    def __init__(
        self,
        session_id: int,
        path: str,
        type_name: str,
        parms: dict[str, _Parm] | None = None,
    ) -> None:
        self._session_id = session_id
        self._path = path
        self._type = _Type(type_name)
        self._parms = parms or {}
        self.children: list[_Node] = []

    def sessionId(self) -> int:
        return self._session_id

    def path(self) -> str:
        return self._path

    def type(self) -> _Type:
        return self._type

    def parm(self, name: str):
        return self._parms.get(name)

    def allSubChildren(self):
        values = []
        for child in self.children:
            values.append(child)
            values.extend(child.allSubChildren())
        return tuple(values)

    def allNodes(self):
        yield self
        yield from self.allSubChildren()

    def glob(self, pattern: str):
        return tuple(child for child in self.children if fnmatch.fnmatchcase(child._path.rsplit("/", 1)[-1], pattern))


class _Hou:
    def __init__(self, root: _Node) -> None:
        self._nodes = {node.path(): node for node in [root, *root.allSubChildren()]}

    def node(self, path: str):
        return self._nodes.get(path)


def test_builtin_extractor_registry_matches_current_spec() -> None:
    assert [(item.name, item.language, item.node_type_names, item.parameter_names) for item in BUILTIN_CODE_EXTRACTORS] == [
        (
            "vex-wrangle",
            "vex",
            ("attribwrangle", "pointwrangle", "primitivewrangle", "vertexwrangle", "volumewrangle", "wrangle"),
            ("snippet",),
        ),
        ("python-node", "python", ("python", "pythonscript"), ("python", "code", "script")),
    ]


def test_physical_capture_uses_raw_values_namespace_matching_and_registered_parms_only(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = _Node(1, "/", "root")
    obj = _Node(2, "/obj", "obj")
    wrangle_parm = _Parm("@P *= 2;")
    wrangle = _Node(3, "/obj/wrangle1", "AttribWrangle::2.0", {"snippet": wrangle_parm, "comment": _Parm("ignored")})
    python_parm = _Parm("print('ok')")
    python = _Node(4, "/obj/python1", "PYTHON", {"python": python_parm})
    unsupported = _Node(5, "/obj/note1", "null", {"script": _Parm("print('not code')")})
    empty = _Node(6, "/obj/python_empty", "python", {"python": _Parm("   \n")})
    root.children = [obj]
    obj.children = [wrangle, python, unsupported, empty]
    monkeypatch.setitem(sys.modules, "hou", _Hou(root))

    output = tmp_path / "result.json"
    request = tmp_path / "request.json"
    request.write_text(
        json.dumps(
            {
                "extractors": [item.to_payload() for item in BUILTIN_CODE_EXTRACTORS],
                "output_path": str(output),
                "path": "/obj/*",
                "recursive": False,
            }
        ),
        encoding="utf-8",
    )

    live_code_capture.run(str(request))
    payload = json.loads(output.read_text(encoding="utf-8"))

    assert [(item["path"], item["language"], item["source"]) for item in payload["nodes"]] == [
        ("/obj/wrangle1", "vex", "@P *= 2;"),
        ("/obj/python1", "python", "print('ok')"),
    ]
    assert wrangle_parm.raw_calls == 1
    assert python_parm.raw_calls == 1


def test_physical_capture_recursive_scope_includes_selected_node_and_descendants(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = _Node(1, "/", "root")
    obj = _Node(2, "/obj", "obj")
    subnet = _Node(3, "/obj/subnet1", "python", {"python": _Parm("parent")})
    child = _Node(4, "/obj/subnet1/child", "python", {"code": _Parm("child")})
    root.children = [obj]
    obj.children = [subnet]
    subnet.children = [child]
    monkeypatch.setitem(sys.modules, "hou", _Hou(root))

    output = tmp_path / "result.json"
    request = tmp_path / "request.json"
    request.write_text(
        json.dumps(
            {
                "extractors": [item.to_payload() for item in BUILTIN_CODE_EXTRACTORS],
                "output_path": str(output),
                "path": "/obj/subnet1",
                "recursive": True,
            }
        ),
        encoding="utf-8",
    )

    live_code_capture.run(str(request))
    payload = json.loads(output.read_text(encoding="utf-8"))

    assert [item["path"] for item in payload["nodes"]] == [
        "/obj/subnet1",
        "/obj/subnet1/child",
    ]


class _Resolver:
    def __init__(self) -> None:
        self.calls: list[int | None] = []
        self.resolved = object()

    def resolve(self, session=None):
        self.calls.append(session)
        return self.resolved


class _Capture:
    def __init__(self, responses: list[list[LiveCodeEntry]]) -> None:
        self.responses = list(responses)
        self.calls = []

    def capture(self, session, *, path=None, recursive=False):
        self.calls.append((session, path, recursive))
        return self.responses.pop(0)


class _Ranker:
    def __init__(self) -> None:
        self.hybrid_calls = []
        self.dense_calls = []

    def hybrid(self, entries, query, *, top_k):
        entries = list(entries)
        self.hybrid_calls.append((entries, query, top_k))
        return [RankedLiveCode(entries[0], 0.030127891)] if entries else []

    def dense(self, entries, query_source, *, top_k):
        entries = list(entries)
        self.dense_calls.append((entries, query_source, top_k))
        return [RankedLiveCode(entries[0], 0.87654321)] if entries else []


class _Resources:
    def __init__(self) -> None:
        self.payloads: list[str] = []

    def put_text(self, text: str):
        self.payloads.append(text)
        return SimpleNamespace(semantic_alias=f"resource-code-{len(self.payloads):03d}")


def _entry(session_id: int, path: str, language: str, source: str, *, slot="slot") -> LiveCodeEntry:
    return LiveCodeEntry(
        session_id=session_id,
        path=path,
        node_type="python" if language == "python" else "attribwrangle",
        slot_id=slot,
        parameter_name="python" if language == "python" else "snippet",
        language=language,
        source=source,
    )


def test_live_query_search_filters_language_and_returns_resource_backed_exact_hit_shape() -> None:
    python_entry = _entry(1, "/obj/python1", "python", "print('python')")
    vex_entry = _entry(2, "/obj/wrangle1", "vex", "@P *= 2;")
    resolver = _Resolver()
    capture = _Capture([[python_entry, vex_entry]])
    ranker = _Ranker()
    resources = _Resources()
    service = LiveCodeSearchService(resolver, capture, ranker, resources)

    result = service.search(
        language="python",
        query="create geometry",
        like=None,
        top_k=7,
        path="/obj/*",
        recursive=True,
        session=4,
    )

    assert capture.calls == [(resolver.resolved, "/obj/*", True)]
    assert resolver.calls == [4]
    assert ranker.hybrid_calls == [([python_entry], "create geometry", 7)]
    assert resources.payloads == ["print('python')"]
    assert list(result) == ["hits"]
    assert list(result["hits"][0]) == ["path", "node_type", "resource", "score"]
    assert result["hits"][0]["path"] == "/obj/python1"
    assert result["hits"][0]["resource"] == "resource-code-001"
    assert result["hits"][0]["score"].token == "301.278910"
    assert "source" not in result["hits"][0]


def test_like_search_recaptures_exact_source_outside_candidate_scope_and_excludes_source_path() -> None:
    candidate = _entry(2, "/obj/geo1/python2", "python", "candidate")
    same_source_path = _entry(3, "/obj/source", "python", "old source")
    exact_source_a = _entry(3, "/obj/source", "python", "first", slot="a")
    exact_source_b = _entry(3, "/obj/source", "python", "second", slot="b")
    resolver = _Resolver()
    capture = _Capture([[candidate], [exact_source_b, exact_source_a]])
    ranker = _Ranker()
    resources = _Resources()
    service = LiveCodeSearchService(resolver, capture, ranker, resources)

    result = service.search(
        language="python",
        query=None,
        like=same_source_path.path,
        path="/obj/geo1/*",
        recursive=False,
    )

    assert capture.calls == [
        (resolver.resolved, "/obj/geo1/*", False),
        (resolver.resolved, "/obj/source", False),
    ]
    assert ranker.dense_calls == [([candidate], "first\n\nsecond", 10)]
    assert result["hits"][0]["score"].token == "876.543210"


def test_like_search_excludes_source_node_from_candidates_when_in_scope() -> None:
    source = _entry(1, "/obj/source", "python", "source")
    other = _entry(2, "/obj/other", "python", "other")
    resolver = _Resolver()
    capture = _Capture([[source, other]])
    ranker = _Ranker()
    service = LiveCodeSearchService(resolver, capture, ranker, _Resources())

    service.search(language="python", query=None, like="/obj/source")

    assert len(capture.calls) == 1
    assert ranker.dense_calls == [([other], "source", 10)]


@pytest.mark.parametrize(
    ("query", "like"),
    [(None, None), ("query", "/obj/python1")],
)
def test_invalid_query_mode_is_rejected_before_session_resolution(query, like) -> None:
    resolver = _Resolver()
    service = LiveCodeSearchService(resolver, _Capture([]), _Ranker(), _Resources())

    with pytest.raises(BridgeError) as caught:
        service.search(language="python", query=query, like=like)

    assert caught.value.code == "invalid_code_search_query"
    assert resolver.calls == []


def test_no_matching_live_code_returns_empty_hits_without_resource_writes() -> None:
    resolver = _Resolver()
    resources = _Resources()
    service = LiveCodeSearchService(resolver, _Capture([[]]), _Ranker(), resources)

    assert service.search(language="vex", query="noise", like=None) == {"hits": []}
    assert resources.payloads == []


def test_capture_deduplicates_multiple_selected_references_by_session_id(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = _Node(1, "/", "root")
    obj = _Node(2, "/obj", "obj")
    python = _Node(3, "/obj/python1", "python", {"python": _Parm("print(1)")})
    root.children = [obj]
    obj.children = [python]
    obj.glob = lambda _pattern: (python, python)  # type: ignore[method-assign]
    monkeypatch.setitem(sys.modules, "hou", _Hou(root))

    output = tmp_path / "result.json"
    request = tmp_path / "request.json"
    request.write_text(
        json.dumps(
            {
                "extractors": [item.to_payload() for item in BUILTIN_CODE_EXTRACTORS],
                "output_path": str(output),
                "path": "/obj/*",
                "recursive": False,
            }
        ),
        encoding="utf-8",
    )

    live_code_capture.run(str(request))

    assert [item["path"] for item in json.loads(output.read_text(encoding="utf-8"))["nodes"]] == [
        "/obj/python1"
    ]
