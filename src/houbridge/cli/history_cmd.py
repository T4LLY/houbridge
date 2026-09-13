from __future__ import annotations

import typer

from houbridge.cli.common import create_cli_app, emit_result, terminate_with_bridge_error
from houbridge.config import HoubridgeConfig, load_config
from houbridge.errors import BridgeError
from houbridge.history.reader import HistoryReadService, HistoryReader
from houbridge.history.search import HistorySearchService
from houbridge.history.service import HistoryStorageService
from houbridge.houdini.transport import HoudiniTransport
from houbridge.output.policy import OutputPolicy
from houbridge.paths import GlobalDataPaths
from houbridge.search.embedding import Model2VecEmbeddingProvider
from houbridge.session.probe import SessionProbe
from houbridge.session.registry import SessionRegistry
from houbridge.session.resolver import ResolvedSession, SessionResolver


history_app = create_cli_app(no_args_is_help=True, help="Recall and search current-session Action History.")


def _resolve(settings: HoubridgeConfig, session_number: int | None) -> tuple[GlobalDataPaths, ResolvedSession]:
    paths = GlobalDataPaths.from_data_dir(settings.storage.data_dir)
    registry = SessionRegistry(paths.sessions_registry)
    probe = SessionProbe(lambda: HoudiniTransport.from_config(settings.houdini))
    return paths, SessionResolver(registry, probe).resolve(session_number)


def _parse_positive_integer(value: str, *, option: str, maximum: int | None = None) -> int:
    try:
        parsed = int(value, 10)
    except ValueError as exc:
        raise BridgeError(f"invalid_history_{option}", f"--{option.replace('_', '-')} must be an integer.") from exc
    if parsed <= 0 or (maximum is not None and parsed > maximum):
        if maximum is None:
            message = f"--{option.replace('_', '-')} must be a positive integer."
        else:
            message = f"--{option.replace('_', '-')} must be an integer from 1 through {maximum}."
        raise BridgeError(f"invalid_history_{option}", message)
    return parsed


def _parse_history_id(value: str) -> int:
    try:
        parsed = int(value, 10)
    except ValueError as exc:
        raise BridgeError("invalid_history_id", "HISTORY_ID must be a positive integer.") from exc
    if parsed <= 0:
        raise BridgeError("invalid_history_id", "HISTORY_ID must be a positive integer.")
    return parsed


@history_app.command("search", help="Search execution history.")
def search_command(
    query: str = typer.Argument(
        ..., metavar="QUERY", help="Query for hybrid Action History search."
    ),
    top_k: str = typer.Option(
        "10", "--top-k", metavar="INTEGER", help="Return at most this many matches."
    ),
    session_number: int | None = typer.Option(
        None, "--session", help="Target this registered session instead of the primary session."
    ),
) -> None:
    try:
        parsed_top_k = _parse_positive_integer(top_k, option="top_k", maximum=50)
        settings = load_config()
        paths, session = _resolve(settings, session_number)
        provider = Model2VecEmbeddingProvider()
        storage = HistoryStorageService(
            paths,
            embedding_provider=provider,
            lock_timeout_seconds=settings.houdini.lock_timeout_seconds,
        ).existing(session.identity)
        payload = HistorySearchService(
            storage,
            provider=provider,
            hybrid=settings.search.hybrid,
        ).search(query, top_k=parsed_top_k)
        emit_result(payload, policy=OutputPolicy.from_config(settings))
    except BridgeError as exc:
        terminate_with_bridge_error(exc)


@history_app.command("get", help="Show a history entry.")
def get_command(
    history_id: str = typer.Argument(
        ..., metavar="HISTORY_ID", help="History entry ID to retrieve."
    ),
    session_number: int | None = typer.Option(
        None, "--session", help="Target this registered session instead of the primary session."
    ),
) -> None:
    try:
        parsed_history_id = _parse_history_id(history_id)
        settings = load_config()
        paths, session = _resolve(settings, session_number)
        storage = HistoryStorageService(
            paths,
            lock_timeout_seconds=settings.houdini.lock_timeout_seconds,
        ).existing(session.identity)
        reader = (
            None
            if storage is None
            else HistoryReader(
                storage.database,
                lock_timeout_seconds=storage.lock_timeout_seconds,
            )
        )
        payload = HistoryReadService(reader).get(parsed_history_id)
        emit_result(payload, policy=OutputPolicy.from_config(settings))
    except BridgeError as exc:
        terminate_with_bridge_error(exc)


@history_app.command("list", help="List history entries.")
def list_command(
    limit: str = typer.Option(
        "20", "--limit", metavar="INTEGER", help="Maximum number of history entries to return."
    ),
    session_number: int | None = typer.Option(
        None, "--session", help="Target this registered session instead of the primary session."
    ),
) -> None:
    try:
        parsed_limit = _parse_positive_integer(limit, option="limit")
        settings = load_config()
        paths, session = _resolve(settings, session_number)
        storage = HistoryStorageService(
            paths,
            lock_timeout_seconds=settings.houdini.lock_timeout_seconds,
        ).existing(session.identity)
        reader = (
            None
            if storage is None
            else HistoryReader(
                storage.database,
                lock_timeout_seconds=storage.lock_timeout_seconds,
            )
        )
        payload = HistoryReadService(reader).list(parsed_limit)
        emit_result(payload, policy=OutputPolicy.from_config(settings))
    except BridgeError as exc:
        terminate_with_bridge_error(exc)
