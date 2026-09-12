from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import tomllib

from houbridge.cli import main as cli_main
from houbridge.cli.common import serialize_result
from houbridge.errors import BridgeError
from houbridge.formatting import (
    SearchScoreMetric,
    format_public_datetime,
    format_search_score,
)



def test_package_installs_one_houbridge_root_console_command() -> None:
    pyproject = tomllib.loads(
        (Path(__file__).parents[2] / "pyproject.toml").read_text(encoding="utf-8")
    )

    assert pyproject["project"]["scripts"] == {
        "houbridge": "houbridge.cli.main:main"
    }

def test_public_datetime_uses_shared_second_precision_formatter() -> None:
    value = datetime(2026, 9, 8, 6, 58, 22, 987654, tzinfo=timezone.utc)

    assert format_public_datetime(value) == "2026-09-08T06:58:22"


def test_dense_score_uses_shared_scaling_and_six_decimal_lexeme() -> None:
    payload = {
        "score": format_search_score(
            "0.30127891",
            metric=SearchScoreMetric.DENSE_COSINE,
        )
    }

    assert serialize_result(payload) == '{"score":301.278910}'


def test_rrf_score_uses_shared_scaling_and_six_decimal_lexeme() -> None:
    payload = {
        "score": format_search_score(
            "0.0317540323",
            metric=SearchScoreMetric.RECIPROCAL_RANK_FUSION,
        )
    }

    assert serialize_result(payload) == '{"score":317.540323}'


def test_cli_main_wraps_bridge_error(monkeypatch, capsys) -> None:
    def explode() -> None:
        raise BridgeError("example_error", "Example failed.", "detail")

    monkeypatch.setattr(cli_main, "app", explode)

    try:
        cli_main.main()
    except SystemExit as exc:
        assert exc.code == 1
    else:
        raise AssertionError("main must exit after a handled BridgeError")

    assert json.loads(capsys.readouterr().out) == {
        "error": True,
        "code": "example_error",
        "message": "Example failed.",
        "detail": "detail",
    }


def test_cli_main_wraps_unexpected_exceptions(monkeypatch, capsys) -> None:
    def explode() -> None:
        raise ValueError("boom")

    monkeypatch.setattr(cli_main, "app", explode)

    try:
        cli_main.main()
    except SystemExit as exc:
        assert exc.code == 1
    else:
        raise AssertionError("main must exit after an unexpected exception")

    assert json.loads(capsys.readouterr().out) == {
        "error": True,
        "code": "internal_error",
        "message": "Houbridge encountered an unexpected internal error.",
        "detail": "ValueError: boom",
    }
