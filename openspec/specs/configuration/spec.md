# Configuration Specification

## Purpose

Define persistent Houbridge configuration, defaults, layering, validation, and feature enablement.

## Requirements

### Requirement: Use global configuration with optional current-directory overrides

Houbridge SHALL use a global `config.toml` as the base configuration and MAY apply `<cwd>/.houbridge.toml` as a deep current-directory override for settings permitted to vary by working directory. Missing local configuration SHALL be normal and SHALL NOT cause a local file to be created automatically. Settings explicitly defined as global-only SHALL be resolved from global configuration rather than from the local override file or an invocation-local storage-path override.

#### Scenario: Run without an existing global config file
- **WHEN** the global Houbridge `config.toml` does not exist
- **THEN** Houbridge creates it with all required tables and generated defaults before loading configuration

#### Scenario: Override one permitted setting for the current directory
- **WHEN** `.houbridge.toml` supplies one nested setting that is permitted to vary locally
- **THEN** that setting overrides the corresponding global value
- **AND** unspecified settings continue to come from the global configuration

#### Scenario: No local config exists
- **WHEN** `<cwd>/.houbridge.toml` is absent
- **THEN** Houbridge uses the global configuration without creating the local file

#### Scenario: Local config is partial
- **WHEN** `<cwd>/.houbridge.toml` contains only a permitted subset of settings
- **THEN** it is accepted as an override layer
- **AND** required completeness is evaluated after merge with global configuration

#### Scenario: Effective config is malformed or incomplete
- **WHEN** TOML parsing fails or the merged effective configuration lacks a required table/value
- **THEN** Houbridge reports an invalid-configuration error

### Requirement: Resolve Houbridge settings from configuration and invocation arguments

Houbridge-specific persistent settings SHALL come from TOML configuration or explicit invocation arguments. Standard Houdini/SideFX discovery environment such as `HFS` and standard third-party cache environment variables MAY be honored for their native purposes.

#### Scenario: An invocation overrides a configurable option
- **WHEN** a command supplies a supported per-invocation override
- **THEN** that invocation uses the explicit value without mutating persistent TOML configuration

### Requirement: Configure the global operational data directory

`[storage].data_dir` SHALL select the single global Houbridge operational data directory. An empty generated value SHALL resolve to the platform-standard Houbridge user data location. Public commands SHALL NOT provide a per-invocation override for this directory.

#### Scenario: Data directory is empty
- **WHEN** `[storage].data_dir` is the generated empty string
- **THEN** the platform-standard Houbridge user data directory is used for global operational state

#### Scenario: Data directory is configured
- **WHEN** `[storage].data_dir` contains a path
- **THEN** that path is expanded and used for global operational state
- **AND** commands use that same directory regardless of their current working directory


### Requirement: Keep shared operational settings global-only

`[storage].data_dir`, `[resource].ttl_hours`, `[task].max_concurrency`, and `[screenshot].retention_hours` SHALL be global-only settings because they govern stores or coordination shared across working directories. `<cwd>/.houbridge.toml` SHALL NOT override these keys. If a local configuration contains one of these global-only keys, configuration loading SHALL fail as invalid rather than silently applying different policy to the same shared operational state.


#### Scenario: Local config attempts to change Resource TTL
- **WHEN** `<cwd>/.houbridge.toml` contains `[resource].ttl_hours`
- **THEN** configuration loading fails as invalid
- **AND** the shared `resources.db` is not subject to cwd-dependent retention rules

#### Scenario: Local config attempts to change capture retention
- **WHEN** `<cwd>/.houbridge.toml` contains `[screenshot].retention_hours`
- **THEN** configuration loading fails as invalid
- **AND** cleanup policy for the shared managed capture namespace does not vary by cwd

### Requirement: Configure Houdini session target separately from process behavior

`[session].port` SHALL define the default local Houdini openport. `[houdini]` SHALL independently configure explicit `hcommand`/GUI executable overrides and transport, lock, startup, and polling timeouts.

Generated defaults SHALL be:

- `[session].port = 18888`
- `[houdini].hcommand = ""`
- `[houdini].executable = ""`
- `[houdini].transport_timeout_seconds = 120`
- `[houdini].lock_timeout_seconds = 120`
- `[houdini].startup_timeout_seconds = 60`
- `[houdini].startup_poll_interval_seconds = 0.25`

#### Scenario: Current directory selects a Houdini port
- **WHEN** local configuration overrides `[session].port`
- **THEN** Houdini-facing commands in that working directory use the overridden port unless the invocation explicitly selects another permitted port

#### Scenario: Session start explicitly selects a port
- **WHEN** Session start receives an explicit port override
- **THEN** it uses that port for that invocation without mutating persistent configuration

### Requirement: Configure workspace script-search persistence

`[local_script_database].enabled` SHALL control workspace script semantic index creation and refresh. The generated default SHALL be `true`.

#### Scenario: Local script database is disabled
- **WHEN** effective `[local_script_database].enabled` is `false`
- **THEN** local script search does not create or update `.houbridge/search.db`

### Requirement: Configure search embeddings and hybrid ranking

The code embedding profile and hybrid-search parameters SHALL be configurable. Generated defaults SHALL be:

- `[search.embedding].code_profile = "minishlab/potion-code-16M-v2"`
- `[search.hybrid].rrf_k = 60`
- `[search.hybrid].candidate_multiplier = 8`
- `[search.hybrid].candidate_min = 32`

#### Scenario: Search uses configured hybrid parameters
- **WHEN** a hybrid search path is constructed
- **THEN** reciprocal-rank fusion and candidate fan-out use the effective configured values

#### Scenario: Script search uses the code profile
- **WHEN** workspace script semantic search embeds file-level documents and queries
- **THEN** it uses the effective `[search.embedding].code_profile`

### Requirement: Configure Resource inspection

Generated Resource defaults SHALL be:

- `[resource].inline_limit_bytes = 16384`
- `[resource].search_limit = 10`
- `[resource].ttl_hours = 72`

The inspection settings control bounded Resource reading/search. `ttl_hours` controls operational Resource retention and is global-only. These settings SHALL NOT change where Resource payloads are persisted.

#### Scenario: Resource reading uses configured limits
- **WHEN** a text Resource is inspected
- **THEN** the effective Resource inspection limits are applied subject to fixed hard maxima

#### Scenario: Generated Resource retention is used
- **WHEN** no Resource TTL override is configured
- **THEN** Resource retention uses `72` hours
- **AND** Task terminal retention uses that same effective duration


### Requirement: Configure Async Task concurrency only

The generated configuration SHALL define `[task].max_concurrency = 1`. The value SHALL be an integer greater than or equal to `1` and SHALL be global-only. This setting SHALL limit concurrently running Async Tasks sharing the configured global Task store and SHALL NOT count synchronous `exec` invocations as Task slots. Exact Houdini process-incarnation serialization remains fixed at one independently of this setting.

Task SHALL not define a separate TTL configuration; terminal Task retention SHALL use the effective `[resource].ttl_hours`.

#### Scenario: Generated Task configuration is used
- **WHEN** no Task concurrency override is configured
- **THEN** at most one Async Task runs for the configured global Task store

#### Scenario: Task concurrency is increased
- **WHEN** `[task].max_concurrency` is greater than `1`
- **THEN** additional Async Tasks may run only when the Task and exact-process coordination rules permit them


### Requirement: Configure session Action History enablement

The generated configuration SHALL define `[history].enabled = true`. This setting MAY be overridden by `<cwd>/.houbridge.toml` because it controls whether executions originating from that working directory contribute Action History. When the effective value is `false`, Execution and Task Runtime SHALL skip History recorder initialization, History entry creation, and source embedding work for that invocation.

#### Scenario: History uses the generated default
- **WHEN** no History enablement override is supplied
- **THEN** managed Python executions that actually start in Houdini are eligible for session Action History recording

#### Scenario: Local History is disabled
- **WHEN** effective `[history].enabled` is `false`
- **THEN** the invocation does not initialize Action Change capture or write History data

### Requirement: Configure screenshot limits and retention

Generated screenshot defaults SHALL be:

- `[screenshot].retention_hours = 1`
- `[screenshot].max_width = 2048`
- `[screenshot].max_height = 2048`

#### Scenario: Screenshot output is bounded
- **WHEN** a screenshot request would exceed configured dimensions
- **THEN** Capture reduces the output according to the Capture specification

### Requirement: Configure the shared inline-output threshold under Output

The generated configuration SHALL define `[output].inline_max_tokens = 256` as the common soft inline token threshold. The common Output subsystem SHALL consume this value.

#### Scenario: Default config is created
- **WHEN** Houbridge writes a fresh global config
- **THEN** `[output].inline_max_tokens` is `256`
- **AND** feature services do not implement private configured thresholds

### Requirement: Reject configuration above fixed output hard limits

Configurable output limits MAY tighten soft limits but SHALL NOT exceed the fixed hard maxima defined by the Output Policy.

#### Scenario: Global or local configuration exceeds a hard maximum
- **WHEN** a configured inline or Resource search/output limit exceeds its fixed maximum
- **THEN** configuration loading fails as invalid

### Requirement: Cache unchanged TOML parsing without hiding file changes

Configuration loading MAY cache parsed TOML for efficiency, but the cache SHALL be invalidated when the underlying file's observed modification state changes.

#### Scenario: Config file is unchanged
- **WHEN** the same global/local TOML file is loaded repeatedly without modification
- **THEN** Houbridge may reuse the parsed representation

#### Scenario: Config file changes
- **WHEN** file modification metadata/content changes between loads
- **THEN** the next configuration load observes the updated values
