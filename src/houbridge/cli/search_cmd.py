from __future__ import annotations

import typer

from houbridge.cli.common import create_cli_app, emit_result, terminate_with_bridge_error
from houbridge.config import HoubridgeConfig, load_config
from houbridge.errors import BridgeError
from houbridge.output.policy import OutputPolicy
from houbridge.script_search import ScriptSearchService


search_app = create_cli_app(
    no_args_is_help=True,
    help="Search local scripts and current Houdini state.",
)


def _script_service(settings: HoubridgeConfig) -> ScriptSearchService:
    return ScriptSearchService.from_config(settings)


@search_app.command("script")
def search_script(
    query: str,
    top_k: int = typer.Option(10, "--top-k", min=1, max=50),
) -> None:
    try:
        settings = load_config()
        result = _script_service(settings).search(query, top_k=top_k)
        emit_result(result, policy=OutputPolicy.from_config(settings))
    except BridgeError as exc:
        terminate_with_bridge_error(exc)
