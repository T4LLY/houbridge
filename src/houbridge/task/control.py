from __future__ import annotations

from dataclasses import dataclass

from houbridge.config import HoubridgeConfig
from houbridge.paths import GlobalDataPaths

from .activation import TaskRuntimeProcessLauncher
from .runtime_store import TaskRuntimeStateStore
from .store import TaskStore
from .supervisor import TaskRuntimeSupervisor


@dataclass(frozen=True, slots=True)
class TaskRuntimeControl:
    store: TaskStore
    runtime_state: TaskRuntimeStateStore
    supervisor: TaskRuntimeSupervisor
    launcher: TaskRuntimeProcessLauncher


def build_task_runtime_control(config: HoubridgeConfig) -> TaskRuntimeControl:
    paths = GlobalDataPaths.from_data_dir(config.storage.data_dir)
    store = TaskStore(paths.tasks_database)
    runtime_state = TaskRuntimeStateStore(paths.tasks_database)
    supervisor = TaskRuntimeSupervisor(runtime_state)
    launcher = TaskRuntimeProcessLauncher(
        runtime_state=runtime_state,
        tasks_database=paths.tasks_database,
        resources_database=paths.resources_database,
        resource_ttl_hours=config.resource.ttl_hours,
        max_concurrency=config.task.max_concurrency,
        handoff_timeout_seconds=config.houdini.transport_timeout_seconds,
        lock_timeout_seconds=config.houdini.lock_timeout_seconds,
    )
    return TaskRuntimeControl(store, runtime_state, supervisor, launcher)
