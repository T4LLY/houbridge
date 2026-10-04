from __future__ import annotations

import os
import subprocess


def hidden_window_creationflags() -> int:
    """Return Windows flags for helper processes that must not open a console."""

    if os.name != "nt":
        return 0
    return int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
