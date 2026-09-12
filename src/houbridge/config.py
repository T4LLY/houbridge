from __future__ import annotations

import hashlib
import math
import tomllib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

from platformdirs import user_config_path, user_data_path

from houbridge.errors import BridgeError


HARD_INLINE_TOKEN_LIMIT = 4096
HARD_EMIT_LIMIT_BYTES = 65536
HARD_RESOURCE_SEARCH_LIMIT = 100

_DEFAULT_CONFIG = """[storage]
data_dir = ""

[houdini]
hcommand = ""
transport_timeout_seconds = 120
lock_timeout_seconds = 120
startup_timeout_seconds = 60
startup_poll_interval_seconds = 0.25

[local_script_database]
enabled = true

[search.embedding]
code_profile = "minishlab/potion-code-16M-v2"

[search.hybrid]
rrf_k = 60
candidate_multiplier = 8
candidate_min = 32

[resource]
inline_limit_bytes = 16384
search_limit = 10
ttl_hours = 72

[task]
max_concurrency = 1

[history]
enabled = true

[screenshot]
retention_hours = 1
max_width = 2048
max_height = 2048

[output]
inline_max_tokens = 256
"""

_SCHEMA: dict[str, object] = {
    "storage": {"data_dir": None},
    "houdini": {
        "hcommand": None,
        "transport_timeout_seconds": None,
        "lock_timeout_seconds": None,
        "startup_timeout_seconds": None,
        "startup_poll_interval_seconds": None,
    },
    "local_script_database": {"enabled": None},
    "search": {
        "embedding": {"code_profile": None},
        "hybrid": {
            "rrf_k": None,
            "candidate_multiplier": None,
            "candidate_min": None,
        },
    },
    "resource": {
        "inline_limit_bytes": None,
        "search_limit": None,
        "ttl_hours": None,
    },
    "task": {"max_concurrency": None},
    "history": {"enabled": None},
    "screenshot": {
        "retention_hours": None,
        "max_width": None,
        "max_height": None,
    },
    "output": {"inline_max_tokens": None},
}

_GLOBAL_ONLY_KEYS = frozenset(
    {
        ("storage", "data_dir"),
        ("resource", "ttl_hours"),
        ("task", "max_concurrency"),
        ("screenshot", "retention_hours"),
        ("houdini", "hcommand"),
    }
)


@dataclass(frozen=True)
class StorageConfig:
    data_dir: Path


@dataclass(frozen=True)
class HoudiniConfig:
    hcommand: str
    transport_timeout_seconds: float
    lock_timeout_seconds: float
    startup_timeout_seconds: float
    startup_poll_interval_seconds: float


@dataclass(frozen=True)
class LocalScriptDatabaseConfig:
    enabled: bool


@dataclass(frozen=True)
class SearchEmbeddingConfig:
    code_profile: str


@dataclass(frozen=True)
class SearchHybridConfig:
    rrf_k: int
    candidate_multiplier: int
    candidate_min: int


@dataclass(frozen=True)
class SearchConfig:
    embedding: SearchEmbeddingConfig
    hybrid: SearchHybridConfig


@dataclass(frozen=True)
class ResourceConfig:
    inline_limit_bytes: int
    search_limit: int
    ttl_hours: int


@dataclass(frozen=True)
class TaskConfig:
    max_concurrency: int


@dataclass(frozen=True)
class HistoryConfig:
    enabled: bool


@dataclass(frozen=True)
class ScreenshotConfig:
    retention_hours: int
    max_width: int
    max_height: int


@dataclass(frozen=True)
class OutputConfig:
    inline_max_tokens: int


@dataclass(frozen=True)
class HoubridgeConfig:
    storage: StorageConfig
    houdini: HoudiniConfig
    local_script_database: LocalScriptDatabaseConfig
    search: SearchConfig
    resource: ResourceConfig
    task: TaskConfig
    history: HistoryConfig
    screenshot: ScreenshotConfig
    output: OutputConfig


def default_config_path() -> Path:
    return user_config_path("houbridge", ensure_exists=False) / "config.toml"


def default_data_dir() -> Path:
    return user_data_path("houbridge", ensure_exists=False)


def local_config_path(cwd: Path | None = None) -> Path:
    return (cwd or Path.cwd()).resolve() / ".houbridge.toml"


def ensure_config_file(path: Path | None = None) -> Path:
    config_path = path or default_config_path()
    if config_path.exists():
        if not config_path.is_file():
            raise BridgeError("invalid_config", f"Config path is not a file: {config_path}")
        return config_path

    try:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(_DEFAULT_CONFIG, encoding="utf-8")
    except OSError as exc:
        raise BridgeError(
            "invalid_config",
            f"Unable to create config.toml: {config_path}",
            f"{type(exc).__name__}: {exc}",
        ) from exc
    return config_path


def load_config(
    path: Path | None = None,
    *,
    cwd: Path | None = None,
) -> HoubridgeConfig:
    config_path = ensure_config_file(path)
    global_raw = _read_toml(config_path)

    local_path = local_config_path(cwd)
    local_raw: dict[str, object] = {}
    if local_path.exists():
        if not local_path.is_file():
            raise BridgeError("invalid_config", f"Config path is not a file: {local_path}")
        local_raw = _read_toml(local_path)
        _validate_local_overrides(local_raw, local_path)

    merged = _deep_merge(global_raw, local_raw)
    _validate_schema(merged)
    return _parse_config(merged, global_config_dir=config_path.resolve().parent)


def _read_toml(path: Path) -> dict[str, object]:
    try:
        resolved = path.resolve()
        data = resolved.read_bytes()
        stat = resolved.stat()
    except OSError as exc:
        raise BridgeError(
            "invalid_config",
            f"Unable to read TOML config: {path}",
            f"{type(exc).__name__}: {exc}",
        ) from exc

    digest = hashlib.sha256(data).digest()
    try:
        return _read_toml_cached(
            str(resolved),
            stat.st_mtime_ns,
            stat.st_size,
            digest,
            data,
        )
    except tomllib.TOMLDecodeError as exc:
        raise BridgeError(
            "invalid_config",
            f"Unable to read TOML config: {path}",
            f"{type(exc).__name__}: {exc}",
        ) from exc


@lru_cache(maxsize=32)
def _read_toml_cached(
    _path: str,
    _mtime_ns: int,
    _size: int,
    _digest: bytes,
    data: bytes,
) -> dict[str, object]:
    # Metadata keeps normal reloads cheap; the digest prevents same-size/same-mtime
    # rewrites from being hidden by the parse cache.
    return tomllib.loads(data.decode("utf-8"))


def _deep_merge(
    base: Mapping[str, object],
    override: Mapping[str, object],
) -> dict[str, object]:
    merged = dict(base)
    for key, value in override.items():
        current = merged.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            merged[key] = _deep_merge(current, value)
        else:
            merged[key] = value
    return merged


def _validate_local_overrides(raw: Mapping[str, object], path: Path) -> None:
    for table_name, key_name in _GLOBAL_ONLY_KEYS:
        table = raw.get(table_name)
        if isinstance(table, dict) and key_name in table:
            raise BridgeError(
                "invalid_config",
                f"Local config cannot override global-only setting "
                f"[{table_name}].{key_name}: {path}",
            )


def _validate_schema(
    raw: Mapping[str, object],
    schema: Mapping[str, object] = _SCHEMA,
    *,
    prefix: str = "",
) -> None:
    for key, value in raw.items():
        if key not in schema:
            dotted = f"{prefix}.{key}" if prefix else key
            raise BridgeError("invalid_config", f"Unsupported config key: {dotted}")

        child_schema = schema[key]
        if isinstance(child_schema, dict):
            dotted = f"{prefix}.{key}" if prefix else key
            if not isinstance(value, dict):
                raise BridgeError("invalid_config", f"Config [{dotted}] must be a table.")
            _validate_schema(value, child_schema, prefix=dotted)


def _resolve_global_path(value: str, *, global_config_dir: Path) -> Path:
    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    return (global_config_dir / path).resolve()


def _resolve_global_executable(value: str, *, global_config_dir: Path) -> str:
    if not value:
        return ""

    path = Path(value).expanduser()
    if path.is_absolute():
        return str(path)

    # Bare executable names intentionally keep PATH-based discovery semantics.
    # Relative path forms are anchored to the global config, never the caller cwd.
    if value.startswith(".") or any(separator in value for separator in ("/", "\\")):
        return str((global_config_dir / path).resolve())
    return value


def _parse_config(
    raw: Mapping[str, object],
    *,
    global_config_dir: Path,
) -> HoubridgeConfig:
    storage = _table(raw, "storage")
    houdini = _table(raw, "houdini")
    local_script_database = _table(raw, "local_script_database")
    search = _table(raw, "search")
    search_embedding = _table(search, "embedding", prefix="search")
    search_hybrid = _table(search, "hybrid", prefix="search")
    resource = _table(raw, "resource")
    task = _table(raw, "task")
    history = _table(raw, "history")
    screenshot = _table(raw, "screenshot")
    output = _table(raw, "output")

    configured_data_dir = _string(storage, "data_dir", allow_empty=True).strip()
    data_dir = (
        _resolve_global_path(configured_data_dir, global_config_dir=global_config_dir)
        if configured_data_dir
        else default_data_dir()
    )
    configured_hcommand = _string(houdini, "hcommand", allow_empty=True).strip()

    return HoubridgeConfig(
        storage=StorageConfig(data_dir=data_dir),
        houdini=HoudiniConfig(
            hcommand=_resolve_global_executable(
                configured_hcommand,
                global_config_dir=global_config_dir,
            ),
            transport_timeout_seconds=_number(
                houdini, "transport_timeout_seconds", positive=True
            ),
            lock_timeout_seconds=_number(houdini, "lock_timeout_seconds", positive=True),
            startup_timeout_seconds=_number(
                houdini, "startup_timeout_seconds", positive=True
            ),
            startup_poll_interval_seconds=_number(
                houdini, "startup_poll_interval_seconds", positive=True
            ),
        ),
        local_script_database=LocalScriptDatabaseConfig(
            enabled=_boolean(local_script_database, "enabled")
        ),
        search=SearchConfig(
            embedding=SearchEmbeddingConfig(
                code_profile=_string(search_embedding, "code_profile")
            ),
            hybrid=SearchHybridConfig(
                rrf_k=_integer(search_hybrid, "rrf_k", minimum=1),
                candidate_multiplier=_integer(
                    search_hybrid, "candidate_multiplier", minimum=1
                ),
                candidate_min=_integer(search_hybrid, "candidate_min", minimum=1),
            ),
        ),
        resource=ResourceConfig(
            inline_limit_bytes=_integer(
                resource,
                "inline_limit_bytes",
                minimum=1,
                maximum=HARD_EMIT_LIMIT_BYTES,
            ),
            search_limit=_integer(
                resource,
                "search_limit",
                minimum=1,
                maximum=HARD_RESOURCE_SEARCH_LIMIT,
            ),
            ttl_hours=_integer(resource, "ttl_hours", minimum=1),
        ),
        task=TaskConfig(
            max_concurrency=_integer(task, "max_concurrency", minimum=1)
        ),
        history=HistoryConfig(enabled=_boolean(history, "enabled")),
        screenshot=ScreenshotConfig(
            retention_hours=_integer(screenshot, "retention_hours", minimum=1),
            max_width=_integer(screenshot, "max_width", minimum=1),
            max_height=_integer(screenshot, "max_height", minimum=1),
        ),
        output=OutputConfig(
            inline_max_tokens=_integer(
                output,
                "inline_max_tokens",
                minimum=0,
                maximum=HARD_INLINE_TOKEN_LIMIT,
            )
        ),
    )


def _table(
    mapping: Mapping[str, object],
    key: str,
    *,
    prefix: str = "",
) -> dict[str, object]:
    value = mapping.get(key)
    label = f"[{prefix + '.' if prefix else ''}{key}]"
    if not isinstance(value, dict):
        raise BridgeError("invalid_config", f"config.toml {label} must be a table.")
    return value


def _string(
    mapping: Mapping[str, object],
    key: str,
    *,
    allow_empty: bool = False,
) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        qualifier = "a string" if allow_empty else "a non-empty string"
        raise BridgeError("invalid_config", f"config.toml {key} must be {qualifier}.")
    return value


def _integer(
    mapping: Mapping[str, object],
    key: str,
    *,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    value = mapping.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise BridgeError("invalid_config", f"config.toml {key} must be an integer.")
    if minimum is not None and value < minimum:
        raise BridgeError("invalid_config", f"config.toml {key} must be >= {minimum}.")
    if maximum is not None and value > maximum:
        raise BridgeError("invalid_config", f"config.toml {key} must be <= {maximum}.")
    return value


def _number(
    mapping: Mapping[str, object],
    key: str,
    *,
    positive: bool = False,
) -> float:
    value = mapping.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise BridgeError("invalid_config", f"config.toml {key} must be a number.")
    result = float(value)
    if positive and (not math.isfinite(result) or result <= 0):
        raise BridgeError(
            "invalid_config", f"config.toml {key} must be finite and > 0."
        )
    return result


def _boolean(mapping: Mapping[str, object], key: str) -> bool:
    value = mapping.get(key)
    if not isinstance(value, bool):
        raise BridgeError("invalid_config", f"config.toml {key} must be a boolean.")
    return value
