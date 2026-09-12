from __future__ import annotations

from pathlib import Path

import typer

from houbridge.cli.common import emit_result, terminate_with_bridge_error
from houbridge.config import HoubridgeConfig, load_config
from houbridge.errors import BridgeError
from houbridge.execution.presentation import ExecutionResultPresenter
from houbridge.execution.runtime import ExecutionRuntime
from houbridge.execution.service import SynchronousExecutionService
from houbridge.execution.source import prepare_file_invocation
from houbridge.history.execution import SynchronousExecutionHistory
from houbridge.history.service import HistoryStorageService
from houbridge.houdini.transport import HoudiniTransport
from houbridge.output.policy import OutputPolicy
from houbridge.paths import GlobalDataPaths
from houbridge.process_coordination import ManagedExecutionLock
from houbridge.session.probe import SessionProbe
from houbridge.session.registry import SessionRegistry
from houbridge.session.resolver import SessionResolver
from houbridge.temporary_workspace import TemporaryWorkspaceService
from houbridge.task.async_submission import AsyncExecutionSubmitter
from houbridge.task.control import build_task_runtime_control


def exec_command(
    ctx: typer.Context,
    source_file: Path = typer.Option(..., "--file"),
    purpose: str | None = typer.Option(None, "--purpose"),
    async_mode: bool = typer.Option(False, "--async"),
    session_number: int | None = typer.Option(None, "--session", min=1),
) -> None:
    try:
        invocation = prepare_file_invocation(
            source_file,
            args=ctx.args,
            purpose=purpose,
        )
        settings = load_config()
        output_policy = OutputPolicy.from_config(settings)
        if async_mode:
            task_id = _build_async_execution_submitter(settings).submit(
                invocation,
                session=session_number,
            )
            emit_result({"task": task_id}, policy=output_policy)
            return

        service = _build_sync_execution_service(settings, output_policy)
        result = service.execute(invocation, session=session_number)
        emit_result(result.payload, policy=output_policy)
        if result.exit_code:
            raise typer.Exit(result.exit_code)
    except BridgeError as exc:
        terminate_with_bridge_error(exc)


def _build_sync_execution_service(
    settings: HoubridgeConfig,
    output_policy: OutputPolicy,
) -> SynchronousExecutionService:
    paths = GlobalDataPaths.from_data_dir(settings.storage.data_dir)
    registry = SessionRegistry(paths.sessions_registry)
    transport = HoudiniTransport.from_config(settings.houdini)
    probe = SessionProbe(lambda: transport)
    resolver = SessionResolver(registry, probe)
    history = None
    if settings.history.enabled:
        history = SynchronousExecutionHistory(
            HistoryStorageService(
                paths,
                lock_timeout_seconds=settings.houdini.lock_timeout_seconds,
            ),
            requested_code_profile=settings.search.embedding.code_profile,
            resource_store_factory=output_policy.resource_store_factory,
        )
    runtime = ExecutionRuntime(
        transport=transport,
        workspaces=TemporaryWorkspaceService(),
        execution_lock=ManagedExecutionLock(),
        lock_timeout_seconds=settings.houdini.lock_timeout_seconds,
        history=history,
    )
    return SynchronousExecutionService(
        resolver,
        runtime,
        ExecutionResultPresenter(output_policy),
    )


def _build_async_execution_submitter(settings: HoubridgeConfig) -> AsyncExecutionSubmitter:
    paths = GlobalDataPaths.from_data_dir(settings.storage.data_dir)
    registry = SessionRegistry(paths.sessions_registry)
    transport = HoudiniTransport.from_config(settings.houdini)
    probe = SessionProbe(lambda: transport)
    resolver = SessionResolver(registry, probe)
    control = build_task_runtime_control(settings)
    return AsyncExecutionSubmitter(
        resolver,
        transport,
        control.store,
        control.supervisor,
        control.launcher,
        lock_timeout_seconds=settings.houdini.lock_timeout_seconds,
        history_enabled=settings.history.enabled,
        history_code_profile=settings.search.embedding.code_profile,
        ttl_hours=settings.resource.ttl_hours,
    )
