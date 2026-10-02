from __future__ import annotations

import typer

from houbridge.cli.common import create_cli_app, emit_result, terminate_with_bridge_error
from houbridge.config import HoubridgeConfig, load_config
from houbridge.errors import BridgeError
from houbridge.houdini.transport import HoudiniTransport
from houbridge.live_code_search import LiveCodeCapture, LiveCodeSearchService, TransientLiveCodeRanker
from houbridge.live_node_search import LiveNodeCapture, LiveNodeSearchService
from houbridge.output.policy import OutputPolicy
from houbridge.paths import GlobalDataPaths
from houbridge.resource.store import ResourceStore
from houbridge.script_search import ScriptSearchService
from houbridge.search.embedding import Model2VecEmbeddingProvider
from houbridge.session.probe import SessionProbe
from houbridge.session.registry import SessionRegistry
from houbridge.session.resolver import SessionResolver


search_app = create_cli_app(
    no_args_is_help=True,
    help="Search local scripts and current Houdini state.",
)


def _script_service(settings: HoubridgeConfig) -> ScriptSearchService:
    return ScriptSearchService.from_config(settings)


def _live_code_service(settings: HoubridgeConfig) -> LiveCodeSearchService:
    paths = GlobalDataPaths.from_data_dir(settings.storage.data_dir)
    registry = SessionRegistry(paths.sessions_registry)
    transport = HoudiniTransport.from_config(settings.houdini)
    probe = SessionProbe(lambda: transport)
    resolver = SessionResolver(registry, probe)
    provider = Model2VecEmbeddingProvider()
    return LiveCodeSearchService(
        resolver,
        LiveCodeCapture(transport),
        TransientLiveCodeRanker(
            embedding_profile=settings.search.embedding.code_profile,
            provider=provider,
            hybrid=settings.search.hybrid,
        ),
        ResourceStore.from_config(settings),
    )


def _live_node_service(settings: HoubridgeConfig) -> LiveNodeSearchService:
    paths = GlobalDataPaths.from_data_dir(settings.storage.data_dir)
    registry = SessionRegistry(paths.sessions_registry)
    transport = HoudiniTransport.from_config(settings.houdini)
    probe = SessionProbe(lambda: transport)
    resolver = SessionResolver(registry, probe)
    return LiveNodeSearchService(resolver, LiveNodeCapture(transport))


@search_app.command("python", help="Search live Houdini Python code.")
def search_python(
    query: str | None = typer.Argument(None, help="Text query for hybrid code search."),
    top_k: int = typer.Option(10, "--top-k", min=1, max=50, help="Return at most this many matches."),
    like: str | None = typer.Option(
        None, "--like", help="Use code from this Houdini node path as the similarity query."
    ),
    path: str | None = typer.Option(None, "--path", help="Limit capture to this Houdini node path or glob."),
    recursive: bool = typer.Option(False, "--recursive", help="Search recursively below matched paths."),
    session: int | None = typer.Option(
        None, "--session", min=1, help="Target this registered session instead of the primary session."
    ),
) -> None:
    _search_live_code(
        language="python",
        query=query,
        top_k=top_k,
        like=like,
        path=path,
        recursive=recursive,
        session=session,
    )


@search_app.command("vex", help="Search live Houdini VEX code.")
def search_vex(
    query: str | None = typer.Argument(None, help="Text query for hybrid code search."),
    top_k: int = typer.Option(10, "--top-k", min=1, max=50, help="Return at most this many matches."),
    like: str | None = typer.Option(
        None, "--like", help="Use code from this Houdini node path as the similarity query."
    ),
    path: str | None = typer.Option(None, "--path", help="Limit capture to this Houdini node path or glob."),
    recursive: bool = typer.Option(False, "--recursive", help="Search recursively below matched paths."),
    session: int | None = typer.Option(
        None, "--session", min=1, help="Target this registered session instead of the primary session."
    ),
) -> None:
    _search_live_code(
        language="vex",
        query=query,
        top_k=top_k,
        like=like,
        path=path,
        recursive=recursive,
        session=session,
    )


def _search_live_code(
    *,
    language: str,
    query: str | None,
    top_k: int,
    like: str | None,
    path: str | None,
    recursive: bool,
    session: int | None,
) -> None:
    try:
        settings = load_config()
        result = _live_code_service(settings).search(
            language=language,
            query=query,
            like=like,
            top_k=top_k,
            path=path,
            recursive=recursive,
            session=session,
        )
        emit_result(result, policy=OutputPolicy.from_config(settings))
    except BridgeError as exc:
        terminate_with_bridge_error(exc)


@search_app.command("node", help="Search live Houdini nodes.")
def search_node(
    query: str = typer.Argument(..., help="Node name, type, or category text to match."),
    top_k: int = typer.Option(20, "--top-k", min=1, max=100, help="Return at most this many matches."),
    path: str | None = typer.Option(None, "--path", help="Limit capture to this Houdini node path or glob."),
    recursive: bool = typer.Option(False, "--recursive", help="Search recursively below matched paths."),
    session: int | None = typer.Option(
        None, "--session", min=1, help="Target this registered session instead of the primary session."
    ),
) -> None:
    try:
        settings = load_config()
        result = _live_node_service(settings).search(
            query,
            top_k=top_k,
            path=path,
            recursive=recursive,
            session=session,
        )
        emit_result(result, policy=OutputPolicy.from_config(settings))
    except BridgeError as exc:
        terminate_with_bridge_error(exc)


@search_app.command("script", help="Search indexed workspace Python scripts.")
def search_script(
    query: str = typer.Argument(..., help="Semantic query for indexed workspace Python scripts."),
    top_k: int = typer.Option(10, "--top-k", min=1, max=50, help="Return at most this many matches."),
    include_all: bool = typer.Option(False, "--all", help="Include scripts under top-level underscore entries."),
) -> None:
    try:
        settings = load_config()
        result = _script_service(settings).search(query, top_k=top_k, include_all=include_all)
        emit_result(result, policy=OutputPolicy.from_config(settings))
    except BridgeError as exc:
        terminate_with_bridge_error(exc)
