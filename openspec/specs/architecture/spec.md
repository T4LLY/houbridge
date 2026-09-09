# Architecture Specification

## Purpose

Define the implementation boundaries and state ownership rules for Houbridge. Command JSON schemas are specified separately.

## Requirements

### Requirement: Separate host-side code from Houdini-injected code

Host orchestration and Houdini-injected source SHALL be physically separated. Reusable Houdini-injected source SHALL live below `houbridge/houdini/scripts/`, grouped by feature. Host-side services SHALL compose or parameterize those scripts rather than embedding large Houdini programs throughout orchestration modules.

#### Scenario: A feature needs Houdini-side Python
- **WHEN** Session, Capture, Search, Execution, or another Houdini-facing feature needs reusable code to run inside Houdini
- **THEN** that reusable source is implemented below `houbridge/houdini/scripts/<feature>/`
- **AND** the host service contains orchestration, parameterization, transport, and result handling

#### Scenario: An injected script grows large
- **WHEN** one injected script contains separable bootstrap, capture, rendering, query, or execution responsibilities
- **THEN** those responsibilities are split into focused script modules under the owning feature
- **AND** the host service does not absorb those bodies as generated string fragments

### Requirement: Keep Houdini transport serverless and local

Houbridge SHALL control Houdini through Houdini openport and SideFX `hcommand` on the loopback host. Raw `hou` Python SHALL remain the Houdini-side operation language.

#### Scenario: Execute a Houdini operation
- **WHEN** Houbridge needs to run injected Python
- **THEN** it sends an invocation-local script through the selected local Houdini openport
- **AND** the operation does not require a persistent Houbridge process inside Houdini

#### Scenario: A non-loopback target is supplied internally
- **WHEN** transport resolution produces a non-loopback host
- **THEN** transport rejects the target

### Requirement: Keep feature subsystems independently owned

The top-level feature subsystems SHALL be `resource`, `output`, `session`, `capture`, `search`, and `execution`, plus shared configuration, Houdini transport, target coordination, temporary-workspace, temporary-artifact publication, and low-level search primitives. Each feature subsystem SHALL expose a public service boundary and own its feature-specific implementation details.

#### Scenario: Search stores a Resource
- **WHEN** Search needs to preserve a code body or oversized logical result
- **THEN** Search uses the Resource service boundary
- **AND** Search does not open or mutate Resource database tables directly

#### Scenario: Execution sends Python to Houdini
- **WHEN** synchronous Execution dispatches caller-provided file source
- **THEN** Execution uses the shared Houdini transport and target-coordination boundaries
- **AND** transport does not acquire feature-specific persistence responsibilities

#### Scenario: Task Runtime executes queued Python
- **WHEN** Task Runtime dispatches a queued Task
- **THEN** it reuses the shared low-level Houdini execution and target-coordination primitives
- **AND** it does not invoke the public `exec` command recursively
- **AND** Task persistence remains owned by Task rather than transport

### Requirement: Construct only the runtime required by the requested command

The CLI composition root SHALL construct only the services required by the selected command. A feature SHALL NOT require initialization of unrelated databases or feature runtimes merely to execute its own operation.

#### Scenario: Execute Python synchronously
- **WHEN** `houbridge exec --file` is invoked without `--async`
- **THEN** the runtime constructs the execution, transport, target, Resource/output, and configuration dependencies required by that invocation
- **AND** local script-search storage is not opened solely because Execution runs

#### Scenario: Submit Python asynchronously
- **WHEN** `houbridge exec --file --async` is invoked
- **THEN** the submission path constructs the Task persistence/runtime handoff and target-probe dependencies required to create the Task
- **AND** it does not initialize unrelated script-search storage

#### Scenario: Search workspace scripts
- **WHEN** `houbridge search script` is invoked
- **THEN** the workspace script-search runtime is constructed
- **AND** a Houdini connection is not required for that local-only operation

### Requirement: Separate synchronous Execution state from Task operational state

Synchronous Execution SHALL operate on the caller's source, invocation options, transient transport files, and produced output only for the lifetime of that invocation. Async operational state that must survive the submitting CLI SHALL be owned exclusively by Task in the global Task store.

#### Scenario: One synchronous execution completes
- **WHEN** the Houdini invocation and output collection finish
- **THEN** Execution returns the logical result to the common Output subsystem
- **AND** no persistent execution record is required for a later command

#### Scenario: Async submission returns
- **WHEN** `exec --async` successfully returns a Task id
- **THEN** submitted source copy, queue state, streams, target binding, and retention needed after CLI exit belong to Task
- **AND** Execution does not duplicate that state in another database

### Requirement: Coordinate managed Python execution by probed Houdini PID

The shared target-coordination boundary SHALL serialize arbitrary managed Python execution by the actual probed Houdini operating-system PID, not merely by caller command type. Synchronous Exec and Async Task SHALL acquire the same per-PID serialization boundary. Task's configurable global concurrency SHALL remain a separate Task concern.

#### Scenario: Same process is reached by managed executions
- **WHEN** synchronous and asynchronous callers resolve to the same Houdini PID
- **THEN** at most one managed arbitrary Python execution runs in that PID at a time

#### Scenario: Two Houdini processes are independent
- **WHEN** callers resolve to different Houdini PIDs
- **THEN** target coordination permits overlap unless another owning subsystem limit applies

### Requirement: Treat Houdini scene data as live application state

Houbridge SHALL read and modify the active Houdini scene through native Houdini APIs while keeping Houbridge persistence in the external storage scopes defined by this specification set. Scene contents SHALL not be required as Houbridge's own persistence store.

#### Scenario: Open an existing Hip file
- **WHEN** Houbridge connects to a running scene
- **THEN** Session, Capture, Search, and Execution operate on the current native Houdini state
- **AND** their operation does not depend on Houbridge persistence being present inside the scene

### Requirement: Separate semantic base generation from feature ordinal allocation

Shared semantic-id logic SHALL generate a semantic base from caller-supplied semantic text and SHALL accept a caller-supplied fallback stem. It SHALL NOT know whether the caller is Task, Resource, or another feature and SHALL NOT own feature persistence or ordinal counters.

Resource SHALL allocate Resource ordinals in Resource persistence. Task SHALL allocate Task ordinals in `tasks.db`.

#### Scenario: Task requests semantic generation
- **WHEN** Task supplies submitted Python source and fallback stem `task-unknown`
- **THEN** shared semantic logic returns the normal semantic base or the supplied fallback according to its defined fallback condition
- **AND** Task persistence assigns the Task ordinal

#### Scenario: Resource requests semantic generation
- **WHEN** Resource supplies Resource semantic text and its Resource fallback stem
- **THEN** shared semantic logic does not allocate a Resource ordinal
- **AND** Resource persistence owns alias registration and ordinal allocation

### Requirement: Centralize canonical public scalar formatting

Canonical public scalar formatting that must remain identical across features SHALL live in shared formatting/output primitives rather than feature-specific result builders. This includes the shared Search score formatter and the shared public date-time formatter defined by the Search and Command Contract specifications.

#### Scenario: Two Search features expose scores
- **WHEN** different Search services create public hit objects
- **THEN** they use the same shared Search score-formatting boundary

#### Scenario: Multiple command families expose date-times
- **WHEN** more than one feature returns a public date-time field
- **THEN** those values use the same shared public date-time formatter
- **AND** feature modules do not duplicate canonical formatting logic

### Requirement: Centralize temporary artifact publication

Filesystem artifacts returned to callers SHALL be published through one shared temporary-artifact boundary. The boundary SHALL publish only completed files below the operating-system temporary directory, reserve collision-safe paths inside Houbridge-managed namespaces, and return the final filesystem path. Feature services SHALL provide artifact-specific bytes or completed source files and the desired filename stem/extension; they SHALL NOT duplicate temporary-root resolution or partial-file publication logic.

The shared boundary MAY expose cleanup primitives for Houbridge-managed temporary namespaces, while retention policy remains owned by the feature/configuration requirement that invokes cleanup.

#### Scenario: Capture publishes a PNG
- **WHEN** Capture has produced a completed PNG
- **THEN** Capture publishes it through the shared temporary-artifact boundary
- **AND** Capture does not independently resolve its own operating-system temp root

#### Scenario: Resource dump publishes payload bytes
- **WHEN** Resource materializes stored payload bytes as a file
- **THEN** Resource uses the same temporary-artifact boundary
- **AND** no partially written dump path is returned

### Requirement: Centralize all public output limiting

All command payloads SHALL pass through one common Output subsystem. Feature-specific CLI or service modules SHALL NOT implement independent token-limit decisions, Resource fallback rules, or final hard-output checks.

#### Scenario: Session produces a small result
- **WHEN** Session returns its logical result
- **THEN** Session does not apply its own output-budget policy
- **AND** the common Output subsystem decides final presentation

#### Scenario: Capture or Search produces a large structured result
- **WHEN** the serialized result exceeds the configured inline threshold
- **THEN** the common Output subsystem performs Resource fallback according to the Output Policy

### Requirement: Keep Resource persistence database-complete

The Resource subsystem SHALL store Resource payload bytes and Resource metadata in `<workspace-root>/.houbridge/resources.db`, with current working directory as the default workspace root and explicit Resource root selection permitted by the Resource specifications. No sibling Resource payload directory is required.

#### Scenario: Store a Resource
- **WHEN** a Resource is created
- **THEN** its payload, MIME metadata, byte size, token count when applicable, canonical SHA-256 identity, semantic alias, and semantic tag registry are persisted through the Resource database

#### Scenario: Delete the Resource database
- **WHEN** the workspace Resource database is removed
- **THEN** local Resource references from that database may stop resolving
- **AND** unrelated Houbridge features remain structurally independent from that Resource store

### Requirement: Separate live, derived, disposable, and operational state

Houbridge SHALL distinguish live Houdini state, workspace-derived search state, workspace Resource state, and global operational runtime state.

#### Scenario: Live Python/VEX search runs
- **WHEN** current-node code is searched
- **THEN** searchable source is captured from the current Houdini scene for that operation
- **AND** its live search index is not required as persistent workspace state

#### Scenario: Workspace script search runs
- **WHEN** `.houbridge/python` scripts are indexed
- **THEN** derived search structures may live in `<cwd>/.houbridge/search.db`
- **AND** original source remains authoritative in the script files

#### Scenario: A Resource is materialized
- **WHEN** a command needs an operational workspace inspection handle for a payload
- **THEN** that payload belongs to the selected workspace's `.houbridge/resources.db`

#### Scenario: Async Task owns global runtime state
- **WHEN** `exec --async` creates a Task
- **THEN** its queue state, submitted source copy while active, stream chunks, target binding, runtime coordination, and Task ordinal state belong to global `tasks.db`
- **AND** its completion Resource remains workspace-local to the Task origin root

### Requirement: Keep the global data root operational

The global Houbridge data root SHALL contain installation/user-level operational runtime state such as locks, transient command files, and the shared `tasks.db`. Workspace Resource and script-search data SHALL use their workspace-local storage scopes.

#### Scenario: Two working directories use one installation
- **WHEN** independent workspaces use the same Houbridge installation
- **THEN** their `.houbridge/resources.db` and `.houbridge/search.db` stores remain workspace-local
- **AND** global operational locks, temporary coordination, and `tasks.db` may be shared

#### Scenario: Task origin is another workspace
- **WHEN** a global Task completes for origin root `E:/project`
- **THEN** Task runtime state remains global
- **AND** its completion Resource is written to `E:/project/.houbridge/resources.db`

### Requirement: Implement only the current specification set

Implementation behavior SHALL be derived from the requirements present in the current specification set. Unspecified feature persistence, command families, metadata fields, and cross-subsystem dependencies SHALL not be inferred from older implementations.

#### Scenario: Rebuild a subsystem
- **WHEN** an implementation is replaced from these specifications
- **THEN** its public surface and persistence are taken from the current requirements
- **AND** unrelated behavior is not added without a corresponding current requirement
