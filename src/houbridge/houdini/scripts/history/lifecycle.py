from __future__ import annotations

import os
import sys
import types
from pathlib import Path


_STATE_MODULE_NAME = "_houbridge_history_scene_lifecycle_v1"


def install(database_path_value: str) -> int:
    """Bind one process-local callback and return the current scene generation."""

    import hou

    database_path = str(Path(database_path_value).resolve())
    state = sys.modules.get(_STATE_MODULE_NAME)
    if state is None:
        state = types.ModuleType(_STATE_MODULE_NAME)
        state.database_path = database_path
        state.generation = 0

        def on_hip_event(event_type) -> None:
            if event_type not in (
                hou.hipFileEventType.AfterLoad,
                hou.hipFileEventType.AfterClear,
            ):
                return
            state.generation += 1
            _destroy_database(Path(state.database_path))

        state.callback = on_hip_event
        sys.modules[_STATE_MODULE_NAME] = state
        hou.hipFile.addEventCallback(on_hip_event)
    elif getattr(state, "database_path", None) != database_path:
        raise RuntimeError(
            "History lifecycle is already bound to a different database for this Houdini process."
        )

    return int(state.generation)


def current_generation(database_path_value: str) -> int:
    database_path = str(Path(database_path_value).resolve())
    state = sys.modules.get(_STATE_MODULE_NAME)
    if state is None or getattr(state, "database_path", None) != database_path:
        raise RuntimeError("History lifecycle has not been installed for this database.")
    return int(state.generation)


def _destroy_database(database_path: Path) -> None:
    for path in (
        database_path,
        Path(str(database_path) + "-wal"),
        Path(str(database_path) + "-shm"),
        Path(str(database_path) + "-journal"),
    ):
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass
