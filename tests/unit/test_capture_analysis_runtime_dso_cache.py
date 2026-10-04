from __future__ import annotations

from pathlib import Path
import runpy
import sys

import pytest


_KEEPALIVE_ATTR = "_houbridge_capture_native_dsos"


class _FakeInstall:
    def __init__(self, result: int = 1) -> None:
        self.argtypes = None
        self.restype = None
        self.calls = 0
        self._result = result

    def __call__(self) -> int:
        self.calls += 1
        return self._result


class _FakeLibrary:
    def __init__(self, path: str, result: int = 1) -> None:
        self._name = path
        self.houbridgeInstallCaptureSceneHookGate = _FakeInstall(result)


def _runtime() -> dict[str, object]:
    path = (
        Path(__file__).parents[2]
        / "src"
        / "houbridge"
        / "houdini"
        / "scripts"
        / "capture"
        / "analysis_runtime.py"
    )
    return runpy.run_path(str(path))


def test_install_dso_reuses_same_resolved_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delattr(sys, _KEEPALIVE_ATTR, raising=False)
    runtime = _runtime()
    ctypes_module = runtime["ctypes"]
    loaded: list[_FakeLibrary] = []

    def fake_cdll(path: str) -> _FakeLibrary:
        library = _FakeLibrary(path)
        loaded.append(library)
        return library

    monkeypatch.setattr(ctypes_module, "CDLL", fake_cdll)
    install_dso = runtime["install_dso"]
    path = tmp_path / "capture.dll"

    install_dso(path)
    install_dso(path.parent / "." / path.name)

    assert len(loaded) == 1
    assert loaded[0].houbridgeInstallCaptureSceneHookGate.calls == 1
    monkeypatch.delattr(sys, _KEEPALIVE_ATTR, raising=False)
