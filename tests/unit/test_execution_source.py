from __future__ import annotations

from pathlib import Path

import pytest

from houbridge.errors import BridgeError
from houbridge.execution.source import (
    prepare_code_invocation,
    prepare_file_invocation,
    validate_python_source,
)


def test_prepare_code_invocation_has_no_file_provenance_and_preserves_args(
    tmp_path: Path,
) -> None:
    invocation = prepare_code_invocation(
        "result = 1\n",
        args=["--name", "box", "--name", "sphere"],
        purpose="wrapper call",
        origin_cwd=tmp_path,
    )

    assert invocation.source == "result = 1\n"
    assert invocation.source_path is None
    assert invocation.argv == (
        "<houbridge-code>",
        "--name",
        "box",
        "--name",
        "sphere",
    )
    assert invocation.purpose == "wrapper call"
    assert invocation.origin_cwd == str(tmp_path.resolve())


def test_prepare_file_invocation_uses_python_source_encoding_rules(tmp_path: Path) -> None:
    source_path = tmp_path / "latin.py"
    source_path.write_bytes(b'# coding: cp1252\nresult = "caf\xe9"\n')

    invocation = prepare_file_invocation(
        source_path,
        args=["--name", "box"],
        purpose="build geometry",
        origin_cwd=tmp_path,
    )

    assert invocation.source == '# coding: cp1252\nresult = "caf\xe9"\n'
    assert invocation.source_path == str(source_path)
    assert invocation.argv == (str(source_path), "--name", "box")
    assert invocation.purpose == "build geometry"
    assert invocation.origin_cwd == str(tmp_path.resolve())


def test_prepare_file_invocation_preserves_supplied_relative_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    source_path = Path("tool.py")
    source_path.write_text("pass\n", encoding="utf-8")

    invocation = prepare_file_invocation(source_path)

    assert invocation.source_path == "tool.py"
    assert invocation.argv == ("tool.py",)


def test_nul_source_is_rejected_with_stable_error() -> None:
    with pytest.raises(BridgeError) as caught:
        validate_python_source("print('before')\x00print('after')")

    assert caught.value.code == "invalid_python_source"


def test_file_decode_failure_is_bridge_error(tmp_path: Path) -> None:
    source_path = tmp_path / "bad.py"
    source_path.write_bytes(b"# coding: ascii\nresult = '\xff'\n")

    with pytest.raises(BridgeError) as caught:
        prepare_file_invocation(source_path)

    assert caught.value.code == "python_file_read_failed"
