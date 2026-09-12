from __future__ import annotations

from pathlib import Path

from houbridge.paths import GlobalDataPaths, WorkspaceSearchPaths


def test_global_operational_paths_are_independent_of_workspace_cwd(
    tmp_path: Path,
    monkeypatch,
) -> None:
    data_dir = tmp_path / "global-data"
    first_workspace = tmp_path / "workspace-a"
    second_workspace = tmp_path / "workspace-b"
    first_workspace.mkdir()
    second_workspace.mkdir()

    monkeypatch.chdir(first_workspace)
    first = GlobalDataPaths.from_data_dir(data_dir)

    monkeypatch.chdir(second_workspace)
    second = GlobalDataPaths.from_data_dir(data_dir)

    assert first == second
    assert first.sessions_registry == data_dir / "sessions.json"
    assert first.tasks_database == data_dir / "tasks.db"
    assert first.resources_database == data_dir / "resources.db"
    assert first.history_directory == data_dir / "history"


def test_workspace_search_paths_are_separate_for_different_working_directories(
    tmp_path: Path,
) -> None:
    first_workspace = tmp_path / "workspace-a"
    second_workspace = tmp_path / "workspace-b"

    first = WorkspaceSearchPaths.for_cwd(first_workspace)
    second = WorkspaceSearchPaths.for_cwd(second_workspace)

    assert first.python_directory == first_workspace.resolve() / ".houbridge" / "python"
    assert first.search_database == first_workspace.resolve() / ".houbridge" / "search.db"
    assert second.python_directory == second_workspace.resolve() / ".houbridge" / "python"
    assert second.search_database == second_workspace.resolve() / ".houbridge" / "search.db"
    assert first.python_directory != second.python_directory
    assert first.search_database != second.search_database


def test_history_database_is_scoped_below_global_history_by_session_key(
    tmp_path: Path,
) -> None:
    paths = GlobalDataPaths.from_data_dir(tmp_path / "global-data")

    first = paths.history_session("pid-1000-incarnation-a")
    second = paths.history_session("pid-1000-incarnation-b")

    assert first.database == (
        tmp_path / "global-data" / "history" / "pid-1000-incarnation-a" / "history.db"
    )
    assert second.database == (
        tmp_path / "global-data" / "history" / "pid-1000-incarnation-b" / "history.db"
    )
    assert first.database != second.database


def test_workspace_paths_do_not_own_global_operational_databases(tmp_path: Path) -> None:
    workspace = WorkspaceSearchPaths.for_cwd(tmp_path)

    assert workspace.python_directory.parent == tmp_path.resolve() / ".houbridge"
    assert workspace.search_database.parent == tmp_path.resolve() / ".houbridge"
    assert workspace.search_database.name == "search.db"
    assert not hasattr(workspace, "resources_database")
    assert not hasattr(workspace, "tasks_database")
    assert not hasattr(workspace, "sessions_registry")


def test_global_paths_do_not_own_workspace_search_state(tmp_path: Path) -> None:
    global_paths = GlobalDataPaths.from_data_dir(tmp_path / "global-data")

    assert not hasattr(global_paths, "python_directory")
    assert not hasattr(global_paths, "search_database")
    assert not hasattr(global_paths, "workspace_directory")
