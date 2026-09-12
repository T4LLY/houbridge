from __future__ import annotations

from houbridge.cli.common import (
    create_cli_app,
    terminate_with_bridge_error,
    terminate_with_internal_error,
)
from houbridge.errors import BridgeError
from houbridge.cli.session_cmd import session_app


app = create_cli_app(
    no_args_is_help=True,
    help="CLI bridge to a running Houdini session.",
)


app.add_typer(session_app, name="session", help="Inspect registered Houdini sessions.")


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
