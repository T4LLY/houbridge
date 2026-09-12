from __future__ import annotations

import os
from pathlib import Path

import pytest

import houbridge.config as config_module
from houbridge.config import (
    HARD_EMIT_LIMIT_BYTES,
    HARD_INLINE_TOKEN_LIMIT,
    HARD_RESOURCE_SEARCH_LIMIT,
    load_config,
)
from houbridge.errors import BridgeError


def _write_default(path: Path) -> None:
    path.write_text(config_module._DEFAULT_CONFIG, encoding="utf-8")


def _replace(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new), encoding="utf-8")


def test_missing_global_config_is_created_with_current_defaults(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config" / "config.toml"
    data_dir = tmp_path / "platform-data"
    monkeypatch.setattr(config_module, "default_data_dir", lambda: data_dir)

    config = load_config(config_path, cwd=tmp_path)

    assert config_path.is_file()
    assert config.storage.data_dir == data_dir
    assert config.houdini.hcommand == ""
    assert config.houdini.transport_timeout_seconds == 120
    assert config.houdini.lock_timeout_seconds == 120
    assert config.houdini.startup_timeout_seconds == 60
    assert config.houdini.startup_poll_interval_seconds == 0.25
    assert config.local_script_database.enabled is True
    assert config.search.embedding.code_profile == "minishlab/potion-code-16M-v2"
    assert config.search.hybrid.rrf_k == 60
    assert config.search.hybrid.candidate_multiplier == 8
    assert config.search.hybrid.candidate_min == 32
    assert config.resource.inline_limit_bytes == 16384
    assert config.resource.search_limit == 10
    assert config.resource.ttl_hours == 72
    assert config.task.max_concurrency == 1
    assert config.history.enabled is True
    assert config.screenshot.retention_hours == 1
    assert config.screenshot.max_width == 2048
    assert config.screenshot.max_height == 2048
    assert config.output.inline_max_tokens == 256

    generated = config_path.read_text(encoding="utf-8")
    assert "[session]" not in generated
    assert "port =" not in generated
    assert "[execution]" not in generated
    assert "uuid_user_data_key" not in generated
    assert "capture_external_changes" not in generated
    assert "[history.events]" not in generated


def test_missing_local_config_is_not_created(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    _write_default(config_path)

    load_config(config_path, cwd=tmp_path)

    assert not (tmp_path / ".houbridge.toml").exists()


def test_local_partial_override_is_deep_merged(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    _write_default(config_path)
    (tmp_path / ".houbridge.toml").write_text(
        """[history]\nenabled = false\n\n[search.hybrid]\nrrf_k = 91\n""",
        encoding="utf-8",
    )

    config = load_config(config_path, cwd=tmp_path)

    assert config.history.enabled is False
    assert config.search.hybrid.rrf_k == 91
    assert config.search.hybrid.candidate_multiplier == 8
    assert config.resource.ttl_hours == 72


@pytest.mark.parametrize(
    "local_toml",
    [
        '[storage]\ndata_dir = "elsewhere"\n',
        "[resource]\nttl_hours = 5\n",
        "[task]\nmax_concurrency = 2\n",
        "[screenshot]\nretention_hours = 2\n",
        '[houdini]\nhcommand = "hython"\n',
    ],
)
def test_local_config_rejects_global_only_settings(
    tmp_path: Path,
    local_toml: str,
) -> None:
    config_path = tmp_path / "config.toml"
    _write_default(config_path)
    (tmp_path / ".houbridge.toml").write_text(local_toml, encoding="utf-8")

    with pytest.raises(BridgeError, match="global-only") as exc_info:
        load_config(config_path, cwd=tmp_path)

    assert exc_info.value.code == "invalid_config"


def test_global_data_dir_is_expanded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_path = tmp_path / "config.toml"
    _write_default(config_path)
    monkeypatch.setenv("HOME", str(tmp_path))
    _replace(config_path, 'data_dir = ""', 'data_dir = "~/houbridge-data"')

    config = load_config(config_path, cwd=tmp_path)

    assert config.storage.data_dir == tmp_path / "houbridge-data"


def test_global_relative_data_dir_is_anchored_to_global_config(
    tmp_path: Path,
) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    config_path = config_dir / "config.toml"
    _write_default(config_path)
    _replace(config_path, 'data_dir = ""', 'data_dir = "shared-state"')
    workspace_a = tmp_path / "workspace-a"
    workspace_b = tmp_path / "workspace-b"
    workspace_a.mkdir()
    workspace_b.mkdir()

    first = load_config(config_path, cwd=workspace_a)
    second = load_config(config_path, cwd=workspace_b)

    expected = (config_dir / "shared-state").resolve()
    assert first.storage.data_dir == expected
    assert second.storage.data_dir == expected


def test_global_relative_hcommand_path_is_anchored_to_global_config(
    tmp_path: Path,
) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    config_path = config_dir / "config.toml"
    _write_default(config_path)
    _replace(config_path, 'hcommand = ""', 'hcommand = "./houdini-bin/houdini"')
    workspace_a = tmp_path / "workspace-a"
    workspace_b = tmp_path / "workspace-b"
    workspace_a.mkdir()
    workspace_b.mkdir()

    first = load_config(config_path, cwd=workspace_a)
    second = load_config(config_path, cwd=workspace_b)

    expected = str((config_dir / "houdini-bin" / "houdini").resolve())
    assert first.houdini.hcommand == expected
    assert second.houdini.hcommand == expected


def test_global_hcommand_bare_name_keeps_path_lookup_semantics(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    _write_default(config_path)
    _replace(config_path, 'hcommand = ""', 'hcommand = "houdini-custom"')

    config = load_config(config_path, cwd=tmp_path)

    assert config.houdini.hcommand == "houdini-custom"


def test_local_may_override_non_global_houdini_timeout(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    _write_default(config_path)
    (tmp_path / ".houbridge.toml").write_text(
        "[houdini]\ntransport_timeout_seconds = 45\n",
        encoding="utf-8",
    )

    config = load_config(config_path, cwd=tmp_path)

    assert config.houdini.transport_timeout_seconds == 45
    assert config.houdini.lock_timeout_seconds == 120


@pytest.mark.parametrize(
    "key",
    [
        "transport_timeout_seconds",
        "lock_timeout_seconds",
        "startup_timeout_seconds",
        "startup_poll_interval_seconds",
    ],
)
@pytest.mark.parametrize("literal", ["nan", "inf"])
def test_houdini_positive_numeric_settings_reject_non_finite_values(
    tmp_path: Path,
    key: str,
    literal: str,
) -> None:
    config_path = tmp_path / "config.toml"
    _write_default(config_path)
    defaults = {
        "transport_timeout_seconds": "120",
        "lock_timeout_seconds": "120",
        "startup_timeout_seconds": "60",
        "startup_poll_interval_seconds": "0.25",
    }
    _replace(config_path, f"{key} = {defaults[key]}", f"{key} = {literal}")

    with pytest.raises(BridgeError, match="finite and > 0") as exc_info:
        load_config(config_path, cwd=tmp_path)

    assert exc_info.value.code == "invalid_config"


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("inline_max_tokens = 256", f"inline_max_tokens = {HARD_INLINE_TOKEN_LIMIT + 1}", "<= 4096"),
        ("search_limit = 10", f"search_limit = {HARD_RESOURCE_SEARCH_LIMIT + 1}", "<= 100"),
        ("inline_limit_bytes = 16384", f"inline_limit_bytes = {HARD_EMIT_LIMIT_BYTES + 1}", "<= 65536"),
    ],
)
def test_fixed_output_hard_limits_are_rejected(
    tmp_path: Path,
    old: str,
    new: str,
    message: str,
) -> None:
    config_path = tmp_path / "config.toml"
    _write_default(config_path)
    _replace(config_path, old, new)

    with pytest.raises(BridgeError, match=message):
        load_config(config_path, cwd=tmp_path)


def test_task_concurrency_must_be_at_least_one(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    _write_default(config_path)
    _replace(config_path, "max_concurrency = 1", "max_concurrency = 0")

    with pytest.raises(BridgeError, match=">= 1"):
        load_config(config_path, cwd=tmp_path)


@pytest.mark.parametrize(
    "legacy_toml",
    [
        "\n[session]\nport = 18888\n",
        "\n[execution]\ninline_max_tokens = 256\n",
        "\n[history.events]\nposition = true\n",
    ],
)
def test_legacy_configuration_is_not_accepted(
    tmp_path: Path,
    legacy_toml: str,
) -> None:
    config_path = tmp_path / "config.toml"
    _write_default(config_path)
    config_path.write_text(
        config_path.read_text(encoding="utf-8") + legacy_toml,
        encoding="utf-8",
    )

    with pytest.raises(BridgeError, match="Unsupported config key"):
        load_config(config_path, cwd=tmp_path)


def test_malformed_or_incomplete_effective_config_is_invalid(tmp_path: Path) -> None:
    malformed = tmp_path / "malformed.toml"
    malformed.write_text("[storage\n", encoding="utf-8")

    with pytest.raises(BridgeError) as malformed_error:
        load_config(malformed, cwd=tmp_path)
    assert malformed_error.value.code == "invalid_config"

    incomplete = tmp_path / "incomplete.toml"
    incomplete.write_text('[storage]\ndata_dir = ""\n', encoding="utf-8")

    with pytest.raises(BridgeError) as incomplete_error:
        load_config(incomplete, cwd=tmp_path)
    assert incomplete_error.value.code == "invalid_config"


def test_toml_cache_reuses_unchanged_parse(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    _write_default(config_path)
    config_module._read_toml_cached.cache_clear()

    load_config(config_path, cwd=tmp_path)
    before = config_module._read_toml_cached.cache_info()
    load_config(config_path, cwd=tmp_path)
    after = config_module._read_toml_cached.cache_info()

    assert after.hits > before.hits


def test_toml_cache_does_not_hide_same_size_same_mtime_rewrite(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    _write_default(config_path)
    config_module._read_toml_cached.cache_clear()

    first = load_config(config_path, cwd=tmp_path)
    assert first.output.inline_max_tokens == 256
    stat = config_path.stat()

    _replace(config_path, "inline_max_tokens = 256", "inline_max_tokens = 257")
    assert config_path.stat().st_size == stat.st_size
    os.utime(config_path, ns=(stat.st_atime_ns, stat.st_mtime_ns))

    second = load_config(config_path, cwd=tmp_path)
    assert second.output.inline_max_tokens == 257
