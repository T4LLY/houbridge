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
- **THEN** it resolves the selected registered Session and sends an invocation-local script through that Session's recorded local Houdini openport
- **AND** the operation does not require a persistent Houbridge process inside Houdini

#### Scenario: A non-loopback target is supplied internally
- **WHEN** transport resolution produces a non-loopback host
- **THEN** transport rejects the target

### Requirement: Keep feature subsystems independently owned

The top-level feature subsystems SHALL be `resource`, `output`, `session`, `hip`, `capture`, `search`, `execution`, `task`, and `history`, plus shared configuration, Houdini transport, target coordination, temporary-workspace, temporary-artifact publication, canonical formatting, semantic-base generation, and low-level search primitives. Each feature subsystem SHALL expose a public service boundary and own its feature-specific implementation details.

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
- **AND** Task persistence remains owned by Task rather than transport

#### Scenario: Execution records an Action History entry
- **WHEN** History is enabled and managed Python actually starts in Houdini
- **THEN** Execution/Task supply execution context and finalized Action Change data through the History service boundary
- **AND** History owns its session-scoped database, search index, and code embeddings

### Requirement: Construct only the runtime required by the requested command

The CLI composition root SHALL construct only the services required by the selected command. A feature SHALL NOT require initialization of unrelated databases or feature runtimes merely to execute its own operation.

#### Scenario: Execute Python synchronously
- **WHEN** `houbridge exec --file` is invoked without `--async`
- **THEN** the runtime constructs the execution, transport, target, Resource/output, configuration, and enabled History dependencies required by that invocation
- **AND** local script-search storage is not opened solely because Execution runs

#### Scenario: Submit Python asynchronously
- **WHEN** `houbridge exec --file --async` is invoked
- **THEN** the submission path constructs the Task persistence/runtime handoff and target-probe dependencies required to create the Task
- **AND** Task Runtime constructs enabled History dependencies only when the queued invocation actually starts
- **AND** unrelated script-search storage is not initialized

#### Scenario: Search workspace scripts
- **WHEN** `houbridge search script` is invoked
- **THEN** the workspace script-search runtime is constructed
- **AND** a Houdini connection is not required for that local-only operation

#### Scenario: Search current-session Action History
- **WHEN** `houbridge history search` is invoked
- **THEN** the current Houdini session is probed to select its session History database
- **AND** unrelated workspace script-search persistence is not required

### Requirement: Separate invocation state, Task state, and session Action History

Synchronous Execution SHALL own caller source, invocation options, transient transport files, and produced output for the lifetime of the invocation. Async operational state that must survive the submitting CLI SHALL be owned by Task in global `tasks.db`. When History is enabled, finalized AI action-recall data SHALL be written through History into the selected Houdini session database rather than being treated as Execution or Task runtime state.

#### Scenario: One synchronous execution completes
- **WHEN** a managed Python invocation finishes
- **THEN** Execution returns the logical result to the common Output subsystem
- **AND** enabled History may receive one finalized Action History entry for that started invocation

#### Scenario: Async submission returns
- **WHEN** `exec --async` successfully returns a Task id
- **THEN** submitted source copy, queue state, streams, target binding, and retention needed after CLI exit belong to Task
- **AND** no History entry is created merely because a Task was queued

### Requirement: Coordinate managed Python execution by exact Houdini process identity

Managed arbitrary Python execution SHALL be serialized by probed Houdini PID/process-incarnation identity rather than by caller command type. Synchronous Exec and Async Task SHALL acquire the same target serialization boundary. This target coordination SHALL live in a fixed platform-standard per-user Houbridge coordination directory that is independent of `[storage].data_dir`, so changing the configured operational data directory cannot create a second execution lock universe for the same Houdini process. Task's configurable concurrency SHALL remain a separate concern scoped to the single configured global Task store.

#### Scenario: Same process is reached by managed executions
- **WHEN** synchronous and asynchronous callers resolve to the same Houdini process incarnation
- **THEN** at most one managed arbitrary Python execution runs in that process at a time

#### Scenario: Two Houdini processes are independent
- **WHEN** callers resolve to different Houdini process incarnations
- **THEN** target coordination permits overlap unless another owning subsystem limit applies

### Requirement: Treat Houdini scene data as live application state

Houbridge SHALL read and modify the active Houdini scene through native Houdini APIs while keeping Houbridge persistence in the external storage scopes defined by this specification set. Scene contents SHALL not be required as Houbridge's own persistence store.

#### Scenario: Open an existing Hip file
- **WHEN** Houbridge connects to a running scene
- **THEN** Session, Hip, Capture, Search, and Execution operate on the current native Houdini state
- **AND** their operation does not depend on Houbridge persistence being present inside the scene

#### Scenario: Inspect or save the current Hip file
- **WHEN** the Hip subsystem reads or saves the active scene
- **THEN** it uses native `hou.hipFile` APIs in the selected live Houdini process
- **AND** it does not create Houbridge-owned scene persistence or a second scene-state store

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

### Requirement: Separate active invocation workspaces from published temporary artifacts

Execution/Task runtime transport buffers and started/completion markers SHALL use a shared Temporary Workspace boundary distinct from the Temporary Artifact publication boundary. Temporary Workspaces SHALL remain private implementation state, SHALL never be returned as public artifacts, and SHALL be recoverable/cleanable according to active Task ownership.

#### Scenario: Async caller Python starts
- **WHEN** Task Runtime needs stdout/stderr transport buffers and invocation markers
- **THEN** those files are created through the Temporary Workspace boundary
- **AND** they are not exposed through Capture/Resource artifact publication APIs

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

### Requirement: Keep Resource persistence database-complete and global

The Resource subsystem SHALL store Resource payload bytes and Resource metadata in one `resources.db` below the configured global data directory. No sibling Resource payload directory is required. Content addressing and semantic aliasing SHALL operate across all working directories using the same global configuration.

#### Scenario: Store a Resource
- **WHEN** a Resource is created
- **THEN** its payload, MIME metadata, byte size, token count when applicable, canonical SHA-256 identity, semantic alias, retention metadata, and semantic tag registry are persisted through global `resources.db`

#### Scenario: Two working directories store identical payloads
- **WHEN** both invocations use the same configured global data directory
- **THEN** identical Resource bytes resolve to the same canonical payload and semantic alias

### Requirement: Separate live, derived, session, and global operational state

Houbridge SHALL distinguish live Houdini state, workspace-derived script-search state, session-scoped Action History state, global Resource/Task operational state, and invocation-local temporary state.

#### Scenario: Live Python/VEX search runs
- **WHEN** current-node code is searched
- **THEN** searchable source is captured from the current Houdini scene for that operation
- **AND** its live search index is not required as persistent workspace state

#### Scenario: Workspace script search runs
- **WHEN** `.houbridge/python` scripts are indexed
- **THEN** derived search structures may live in `<cwd>/.houbridge/search.db`
- **AND** original source remains authoritative in the script files

#### Scenario: A Resource is materialized
- **WHEN** a command needs an inspectable operational payload handle
- **THEN** that payload belongs to `resources.db` below the configured global data directory

#### Scenario: Async Task owns global runtime state
- **WHEN** `exec --async` creates a Task
- **THEN** its queue state, submitted source copy while active, stream chunks, target binding, runtime coordination, and Task ordinal state belong to global `tasks.db`
- **AND** its completion Resource belongs to global `resources.db`

#### Scenario: Started execution contributes to Action History
- **WHEN** History is enabled for a managed Python invocation in a live Houdini process
- **THEN** its finalized action-recall entry belongs only to that Houdini process incarnation's History database
- **AND** node identity inside that History uses Houdini session-local node ids

### Requirement: Keep the global data directory operational

The configured global Houbridge data directory SHALL own user-level operational state including shared `tasks.db`, shared `resources.db`, and session-scoped History databases below `history/`. Exact-Houdini-process coordination locks SHALL live in the fixed per-user coordination directory defined separately from this configurable data directory. Workspace Python source and rebuildable `.houbridge/search.db` SHALL remain local to the working directory.

#### Scenario: Two working directories use one global data directory
- **WHEN** independent workspaces use the same configured Houbridge global data directory
- **THEN** they share Resource and Task operational stores
- **AND** each workspace keeps its own `.houbridge/python` source and `.houbridge/search.db` derived index

#### Scenario: Different Houdini processes are active
- **WHEN** two Houdini process incarnations are reachable
- **THEN** their Action History databases occupy distinct session directories below `<data-dir>/history/`
- **AND** they do not require persistent scene UUIDs

### Requirement: Keep Skill authoring policy separate from runtime ownership

The Houbridge Skill MAY define mandatory authoring rules for AI-generated workspace scripts, but those rules SHALL not introduce a separate metadata store or runtime persistence boundary. Script descriptions SHALL remain ordinary Python module docstrings in the authoritative `.houbridge/python` files.

#### Scenario: Skill creates a described workspace script
- **WHEN** the Houbridge Skill creates a reusable Python file below `.houbridge/python`
- **THEN** its required description is represented by the file's Python module docstring
- **AND** Search consumes that same docstring without a sidecar description database or custom metadata file

### Requirement: Implement only the current specification set

Implementation behavior SHALL be derived from the requirements present in the current specification set. Unspecified feature persistence, command families, metadata fields, and cross-subsystem dependencies SHALL not be inferred from older implementations.

#### Scenario: Rebuild a subsystem
- **WHEN** an implementation is replaced from these specifications
- **THEN** its public surface and persistence are taken from the current requirements
- **AND** unrelated behavior is not added without a corresponding current requirement
