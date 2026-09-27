from __future__ import annotations

import json

from typer.testing import CliRunner

from houbridge.cli.common import bridge_error_payload, serialize_result
from houbridge.cli.main import app
from houbridge.errors import BridgeError
from houbridge.formatting import CanonicalJsonNumber


runner = CliRunner()


def test_root_help_is_plain_text_without_rich_decoration() -> None:
    result = runner.invoke(app, ["--help"], color=True)

    assert result.exit_code == 0
    assert "\x1b[" not in result.stdout
    assert not any(char in result.stdout for char in "╭╮╰╯│─┏┓┗┛┃━")
    assert "Usage:" in result.stdout
    assert "--install-completion" not in result.stdout
    assert "--show-completion" not in result.stdout


def test_framework_usage_error_remains_plain_text() -> None:
    result = runner.invoke(app, ["--does-not-exist"], color=True)

    assert result.exit_code != 0
    output = result.stdout + result.stderr
    assert "\x1b[" not in output
    assert not any(char in output for char in "╭╮╰╯│─┏┓┗┛┃━")
    assert "No such option" in output
    assert not output.lstrip().startswith("{")


def test_bridge_error_without_detail_has_exact_common_envelope() -> None:
    payload = bridge_error_payload(BridgeError("example_error", "Example failed."))

    assert payload == {
        "error": True,
        "code": "example_error",
        "message": "Example failed.",
    }


def test_bridge_error_with_detail_adds_only_detail() -> None:
    payload = bridge_error_payload(
        BridgeError("example_error", "Example failed.", "diagnostic detail")
    )

    assert payload == {
        "error": True,
        "code": "example_error",
        "message": "Example failed.",
        "detail": "diagnostic detail",
    }


def test_bridge_error_with_context_adds_structured_recovery_data() -> None:
    payload = bridge_error_payload(
        BridgeError(
            "scene_viewer_ambiguous",
            "Multiple Scene Viewer panes are available; specify --pane.",
            context={"panes": [{"name": "panetab1"}, {"name": "panetab4"}]},
        )
    )

    assert payload == {
        "error": True,
        "code": "scene_viewer_ambiguous",
        "message": "Multiple Scene Viewer panes are available; specify --pane.",
        "context": {"panes": [{"name": "panetab1"}, {"name": "panetab4"}]},
    }


def test_compact_json_preserves_non_ascii_and_canonical_number_lexeme() -> None:
    serialized = serialize_result(
        {"name": "日本語", "score": CanonicalJsonNumber("301.278910")}
    )

    assert serialized == '{"name":"日本語","score":301.278910}'
    assert json.loads(serialized) == {"name": "日本語", "score": 301.27891}


def test_root_help_exposes_all_seven_public_command_families() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    for command in ("session", "capture", "resource", "search", "exec", "task", "history"):
        assert command in result.stdout


def test_subcommand_help_has_concise_descriptions() -> None:
    expected = {
        "resource": (
            "Show resource metadata.",
            "Retrieve a resource.",
            "Retrieve a text range from a resource.",
            "Search within a resource.",
            "Write a resource to a temporary file.",
        ),
        "task": (
            "Show task details.",
            "List tasks.",
            "Reset terminal task state and task numbering.",
        ),
        "search": (
            "Search live Houdini Python code.",
            "Search live Houdini VEX code.",
            "Search live Houdini nodes.",
            "Search indexed workspace Python scripts.",
        ),
        "capture": (
            "Capture a Houdini viewport image.",
            "Capture a Houdini window image.",
            "Extract text from an image.",
            "Capture a Houdini turntable animation.",
        ),
        "history": (
            "Search execution history.",
            "Show a history entry.",
            "List history entries.",
        ),
        "session": (
            "Show active Houdini sessions.",
            "Start a new Houdini session.",
            "Set a session as the primary session.",
        ),
    }

    for family, descriptions in expected.items():
        result = runner.invoke(app, [family, "--help"])
        assert result.exit_code == 0
        for description in descriptions:
            assert description in result.stdout
