from __future__ import annotations

import typer

from houbridge.cli.common import create_cli_app, emit_result, terminate_with_bridge_error
from houbridge.config import HoubridgeConfig, load_config
from houbridge.errors import BridgeError
from houbridge.output.policy import OutputPolicy
from houbridge.task.control import build_task_runtime_control
from houbridge.task.service import TaskCommandService


task_app = create_cli_app(no_args_is_help=True, help="Inspect and reset asynchronous Tasks.")


def _service(settings: HoubridgeConfig) -> TaskCommandService:
    control = build_task_runtime_control(settings)
    return TaskCommandService(
        control.store,
        control.supervisor,
        control.launcher,
        ttl_hours=settings.resource.ttl_hours,
    )


@task_app.command("get", help="Show task details.")
def task_get(
    task_id: str = typer.Argument(..., help="Task ID to inspect."),
) -> None:
    try:
        settings = load_config()
        emit_result(
            _service(settings).get(task_id),
            policy=OutputPolicy.from_config(settings),
        )
    except BridgeError as exc:
        terminate_with_bridge_error(exc)


@task_app.command("list", help="List tasks.")
def task_list() -> None:
    try:
        settings = load_config()
        emit_result(
            _service(settings).list(),
            policy=OutputPolicy.from_config(settings),
        )
    except BridgeError as exc:
        terminate_with_bridge_error(exc)


@task_app.command("reset", help="Reset terminal task state and task numbering.")
def task_reset() -> None:
    try:
        settings = load_config()
        emit_result(
            _service(settings).reset(),
            policy=OutputPolicy.from_config(settings),
        )
    except BridgeError as exc:
        terminate_with_bridge_error(exc)
