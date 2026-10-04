from __future__ import annotations

import houbridge.subprocesses as subprocesses


def test_hidden_window_creationflags_is_zero_off_windows(monkeypatch) -> None:
    monkeypatch.setattr(subprocesses.os, "name", "posix")
    assert subprocesses.hidden_window_creationflags() == 0


def test_hidden_window_creationflags_uses_create_no_window_on_windows(monkeypatch) -> None:
    monkeypatch.setattr(subprocesses.os, "name", "nt")
    monkeypatch.setattr(subprocesses.subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    assert subprocesses.hidden_window_creationflags() == 0x08000000
