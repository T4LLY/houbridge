from __future__ import annotations

import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

from houbridge.execution.models import ExecutionInvocation
from houbridge.execution.script import ExecutionScriptBuilder
from houbridge.execution.workspace import collect_outcome, stage_invocation
from houbridge.houdini.scripts.execution.runtime import run
from houbridge.temporary_workspace import TemporaryWorkspaceService


def _request_for(
    tmp_path: Path,
    source: str,
    *,
    source_path: str | None = "caller.py",
    argv: tuple[str, ...] | None = None,
    purpose: str | None = None,
) -> tuple[Path, object]:
    workspace = TemporaryWorkspaceService(temp_root=tmp_path).allocate(prefix="exec")
    if argv is None:
        argv = (source_path,) if source_path is not None else ()
    invocation = ExecutionInvocation(
        source=source,
        source_path=source_path,
        argv=argv,
        purpose=purpose,
        origin_cwd=str(tmp_path),
    )
    return stage_invocation(workspace, invocation), workspace


def _install_fake_hou(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "hou", ModuleType("hou"))


def test_runtime_preserves_file_main_argv_and_purpose_is_not_injected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_hou(monkeypatch)
    request, workspace = _request_for(
        tmp_path,
        "import sys\nresult = {'argv': sys.argv, 'file': __file__, 'name': __name__, 'purpose': globals().get('purpose')}\n",
        source_path="relative/tool.py",
        argv=("relative/tool.py", "--node", "/obj/geo1"),
        purpose="build preview geometry",
    )

    run(str(request))
    outcome = collect_outcome(workspace)  # type: ignore[arg-type]

    assert outcome.python_ok is True
    assert outcome.result is not None
    assert outcome.result.inline_value() == {
        "argv": ["relative/tool.py", "--node", "/obj/geo1"],
        "file": "relative/tool.py",
        "name": "__main__",
        "purpose": None,
    }


def test_runtime_direct_source_omits_file_provenance_and_preserves_script_argv(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_hou(monkeypatch)
    request, workspace = _request_for(
        tmp_path,
        "import sys\nresult = {'argv': sys.argv, 'has_file': '__file__' in globals(), 'name': __name__}\n",
        source_path=None,
        argv=("<houbridge-code>", "--node", "/obj/geo1"),
    )

    run(str(request))
    outcome = collect_outcome(workspace)  # type: ignore[arg-type]

    assert outcome.python_ok is True
    assert outcome.result is not None
    assert outcome.result.inline_value() == {
        "argv": ["<houbridge-code>", "--node", "/obj/geo1"],
        "has_file": False,
        "name": "__main__",
    }


def test_runtime_restores_houdini_sys_argv_when_user_source_raises(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_hou(monkeypatch)
    request, workspace = _request_for(
        tmp_path,
        "raise RuntimeError('boom')\n",
        argv=("caller.py", "one"),
    )
    previous = sys.argv

    run(str(request))

    assert sys.argv is previous
    outcome = collect_outcome(workspace)  # type: ignore[arg-type]
    assert outcome.python_ok is False
    assert outcome.result is None
    assert outcome.traceback is not None
    assert "RuntimeError: boom" in outcome.traceback


def test_runtime_captures_stdout_stderr_and_failure_independently(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_hou(monkeypatch)
    request, workspace = _request_for(
        tmp_path,
        "import sys\nprint('out')\nprint('err', file=sys.stderr)\nraise ValueError('bad')\n",
    )

    run(str(request))
    outcome = collect_outcome(workspace)  # type: ignore[arg-type]

    assert outcome.stdout == "out\n"
    assert outcome.stderr == "err\n"
    assert outcome.traceback is not None
    assert "ValueError: bad" in outcome.traceback


@pytest.mark.parametrize(
    ("source", "kind", "inline"),
    [
        ("result = '{\"name\":\"box\",\"count\":3}'", "json", {"name": "box", "count": 3}),
        ("result = 'plain text'", "text", "plain text"),
        ("result = {'items': [1, 2], 'ok': True}", "json", {"items": [1, 2], "ok": True}),
        ("result = b'\\x00\\xff'", "text", "b'\\x00\\xff'"),
    ],
)
def test_runtime_classifies_declared_result_deterministically(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    source: str,
    kind: str,
    inline: object,
) -> None:
    _install_fake_hou(monkeypatch)
    request, workspace = _request_for(tmp_path, source)

    run(str(request))
    outcome = collect_outcome(workspace)  # type: ignore[arg-type]

    assert outcome.python_ok is True
    assert outcome.result is not None
    assert outcome.result.kind == kind
    assert outcome.result.inline_value() == inline


def test_runtime_uses_bounded_repr_for_non_json_object(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_hou(monkeypatch)
    request, workspace = _request_for(
        tmp_path,
        "class Huge:\n    def __repr__(self):\n        return 'x' * 10000\nresult = Huge()\n",
    )

    run(str(request))
    outcome = collect_outcome(workspace)  # type: ignore[arg-type]

    assert outcome.result is not None
    assert outcome.result.kind == "text"
    assert len(outcome.result.payload) < 200


def test_runtime_non_json_object_with_broken_repr_still_becomes_text(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_hou(monkeypatch)
    request, workspace = _request_for(
        tmp_path,
        "class Broken:\n    def __repr__(self):\n        raise RuntimeError('no repr')\nresult = Broken()\n",
    )

    run(str(request))
    outcome = collect_outcome(workspace)  # type: ignore[arg-type]

    assert outcome.python_ok is True
    assert outcome.result is not None
    assert outcome.result.kind == "text"
    assert len(outcome.result.inline_value()) < 200


def test_builder_only_parameterizes_physical_execution_runtime(tmp_path: Path) -> None:
    workspace = TemporaryWorkspaceService(temp_root=tmp_path).allocate(prefix="exec")
    request = workspace.path_for("request.json")
    request.write_text("{}", encoding="utf-8")

    staged = ExecutionScriptBuilder().stage(workspace, request)
    script = staged.script_path.read_text(encoding="utf-8")

    assert "runpy.run_path" in script
    assert "contextlib.redirect_stdout" not in script
    from houbridge.houdini.scripts.execution import runtime as physical_runtime

    assert Path(physical_runtime.__file__).parent.name == "execution"
    assert Path(physical_runtime.__file__).parent.parent.name == "scripts"
