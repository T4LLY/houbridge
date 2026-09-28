from __future__ import annotations

from houbridge.cli.common import (
    create_cli_app,
    terminate_with_bridge_error,
    terminate_with_internal_error,
)
from houbridge.errors import BridgeError
from houbridge.cli.capture_cmd import capture_app
from houbridge.cli.exec_cmd import exec_command
from houbridge.cli.history_cmd import history_app
from houbridge.cli.resource_cmd import resource_app
from houbridge.cli.search_cmd import search_app
from houbridge.cli.session_cmd import session_app
from houbridge.cli.task_cmd import task_app


app = create_cli_app(
    no_args_is_help=True,
    help="CLI bridge to a running Houdini session.",
)


app.add_typer(session_app, name="session", help="Create and inspect registered Houdini sessions.")
app.add_typer(
    capture_app,
    name="capture",
    help="Capture or inspect Houdini views and cameras.",
)
app.add_typer(resource_app, name="resource", help="Inspect and materialize stored Resources.")
app.add_typer(search_app, name="search", help="Search local scripts and current Houdini state.")
app.add_typer(task_app, name="task", help="Inspect and reset asynchronous Tasks.")
app.add_typer(history_app, name="history", help="Recall and search current-session Action History.")
app.command(
    "exec",
    help="Execute a Python file in Houdini. Trailing arguments are passed to the script.",
    context_settings={"allow_extra_args": True},
)(exec_command)


@app.callback()
def _root() -> None:
    """Houbridge root command."""


def main() -> None:
    try:
        app()
    except BridgeError as exc:
        terminate_with_bridge_error(exc)
    except Exception as exc:
        terminate_with_internal_error(exc)


if __name__ == "__main__":
    main()
