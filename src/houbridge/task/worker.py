from __future__ import annotations

import argparse
from pathlib import Path

from houbridge.history.service import HistoryStorageService
from houbridge.paths import GlobalDataPaths
from houbridge.resource.store import ResourceStore
from houbridge.temporary_workspace import TemporaryWorkspaceService

from .completion import TaskCompletionResourceFinalizer
from .history import AsyncTaskHistory
from .invocation_store import TaskInvocationStore
from .runner import TaskInvocationRunner
from .runtime import TaskRuntime
from .runtime_store import TaskRuntimeStateStore
from .store import TaskStore


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--owner-token", required=True)
    parser.add_argument("--tasks-db", type=Path, required=True)
    parser.add_argument("--resources-db", type=Path, required=True)
    parser.add_argument("--resource-ttl-hours", type=int, required=True)
    parser.add_argument("--max-concurrency", type=int, required=True)
    args = parser.parse_args(argv)

    task_store = TaskStore(args.tasks_db)
    runtime_state = TaskRuntimeStateStore(args.tasks_db)
    invocations = TaskInvocationStore(args.tasks_db)
    resource_store = ResourceStore(
        args.resources_db,
        ttl_hours=args.resource_ttl_hours,
    )
    finalizer = TaskCompletionResourceFinalizer(task_store, resource_store)
    paths = GlobalDataPaths.from_data_dir(args.tasks_db.resolve().parent)
    history = AsyncTaskHistory(
        HistoryStorageService(paths),
        resource_store=resource_store,
    )
    runner = TaskInvocationRunner(
        task_store,
        invocations,
        TemporaryWorkspaceService(),
        finalizer,
        history=history,
    )
    runtime = TaskRuntime(
        task_store,
        runtime_state,
        runner,
        max_concurrency=args.max_concurrency,
    )
    runtime.run(args.owner_token)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
