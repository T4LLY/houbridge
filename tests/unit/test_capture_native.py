from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

from houbridge.capture.native import NativeCaptureBuilder, _require_gate_success
from houbridge.errors import BridgeError


def _source_dir(root: Path) -> Path:
    source = root / "native"
    source.mkdir()
    (source / "scene_hook_gate.C").write_text("int source = 1;\n", encoding="utf-8")
    return source


def _houdini_bin(root: Path) -> tuple[Path, Path]:
    bin_dir = root / "Houdini22.0.429" / "bin"
    bin_dir.mkdir(parents=True)
    hcommand = bin_dir / "hcommand.exe"
    hcustom = bin_dir / "hcustom.exe"
    hcommand.write_bytes(b"")
    hcustom.write_bytes(b"")
    return hcommand, hcustom


def test_native_builder_caches_by_houdini_build_and_source_hash(tmp_path: Path) -> None:
    source = _source_dir(tmp_path)
    hcommand, hcustom = _houdini_bin(tmp_path)
    calls: list[dict[str, object]] = []

    def fake_run(args, **kwargs):
        calls.append({"args": args, "kwargs": kwargs})
        dso_dir = Path(args[2])
        source_path = Path(args[3])
        (dso_dir / f"{source_path.stem}.dll").write_bytes(b"dso")
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="built", stderr="")

    builder = NativeCaptureBuilder(
        tmp_path / "cache",
        source_dir=source,
        run=fake_run,
    )
    first = builder.ensure(houdini_build="22.0.429", hcommand=hcommand, environ={"PATH": ""})
    second = builder.ensure(houdini_build="22.0.429", hcommand=hcommand, environ={"PATH": ""})

    assert first == second
    assert first.path.is_file()
    assert first.path.parent.parent.name == first.generation
    assert first.path.parent.parent.parent.name == "houdini-22.0.429"
    assert len(calls) == 1
    assert calls[0]["args"][0] == str(hcustom.resolve())  # type: ignore[index]
    assert calls[0]["kwargs"]["stdout"] is subprocess.PIPE  # type: ignore[index]
    assert calls[0]["kwargs"]["stderr"] is subprocess.PIPE  # type: ignore[index]


def test_native_builder_uses_new_generation_when_source_changes(tmp_path: Path) -> None:
    source = _source_dir(tmp_path)
    hcommand, _hcustom = _houdini_bin(tmp_path)
    calls = 0

    def fake_run(args, **kwargs):
        nonlocal calls
        calls += 1
        dso_dir = Path(args[2])
        source_path = Path(args[3])
        (dso_dir / f"{source_path.stem}.dll").write_bytes(b"dso")
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    builder = NativeCaptureBuilder(tmp_path / "cache", source_dir=source, run=fake_run)
    first = builder.ensure(houdini_build="22.0.429", hcommand=hcommand)
    (source / "scene_hook_gate.C").write_text("int source = 2;\n", encoding="utf-8")
    second = builder.ensure(houdini_build="22.0.429", hcommand=hcommand)

    assert first.generation != second.generation
    assert first.path.is_file()
    assert second.path.is_file()
    assert calls == 2


def test_native_builder_separates_houdini_builds(tmp_path: Path) -> None:
    source = _source_dir(tmp_path)
    hcommand, _hcustom = _houdini_bin(tmp_path)

    def fake_run(args, **kwargs):
        dso_dir = Path(args[2])
        source_path = Path(args[3])
        (dso_dir / f"{source_path.stem}.dll").write_bytes(b"dso")
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    builder = NativeCaptureBuilder(tmp_path / "cache", source_dir=source, run=fake_run)
    first = builder.ensure(houdini_build="22.0.429", hcommand=hcommand)
    second = builder.ensure(houdini_build="22.0.430", hcommand=hcommand)

    assert first.generation == second.generation
    assert first.path != second.path
    assert "houdini-22.0.429" in first.path.parts
    assert "houdini-22.0.430" in second.path.parts


def test_native_builder_bounds_compile_failure_diagnostics(tmp_path: Path) -> None:
    source = _source_dir(tmp_path)
    hcommand, _hcustom = _houdini_bin(tmp_path)

    def fake_run(args, **kwargs):
        return subprocess.CompletedProcess(
            args=args,
            returncode=1,
            stdout="x" * 5000,
            stderr="compiler failed",
        )

    builder = NativeCaptureBuilder(tmp_path / "cache", source_dir=source, run=fake_run)
    with pytest.raises(BridgeError) as caught:
        builder.ensure(houdini_build="22.0.429", hcommand=hcommand)

    assert caught.value.code == "capture_native_compile_failed"
    assert caught.value.detail is not None
    assert "compiler failed" in caught.value.detail
    assert len(caught.value.detail) < 8200


def test_native_builder_reports_missing_hcustom(tmp_path: Path) -> None:
    source = _source_dir(tmp_path)
    bin_dir = tmp_path / "Houdini22.0.429" / "bin"
    bin_dir.mkdir(parents=True)
    hcommand = bin_dir / "hcommand.exe"
    hcommand.write_bytes(b"")
    builder = NativeCaptureBuilder(tmp_path / "cache", source_dir=source)

    with pytest.raises(BridgeError) as caught:
        builder.ensure(houdini_build="22.0.429", hcommand=hcommand)

    assert caught.value.code == "capture_native_compiler_not_found"


def test_gate_result_preserves_structured_scenehook_failure(tmp_path: Path) -> None:
    result = tmp_path / "result.json"
    result.write_text(
        json.dumps(
            {
                "ok": False,
                "code": "capture_native_scenehook_unverified",
                "message": "SceneHook was not reached.",
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(BridgeError) as caught:
        _require_gate_success(result)

    assert caught.value.code == "capture_native_scenehook_unverified"
    assert caught.value.message == "SceneHook was not reached."


def test_native_gate_uses_cloned_scene_flipbook_without_scene_nodes() -> None:
    source = (
        Path(__file__).parents[2]
        / "src"
        / "houbridge"
        / "houdini"
        / "scripts"
        / "capture"
        / "native_gate.py"
    ).read_text(encoding="utf-8")

    assert ".clone()" in source
    assert ".flipbook(" in source
    assert "outputToMPlay(False)" in source
    assert "createNode" not in source
    assert "destroy()" not in source
