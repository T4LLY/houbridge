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

The top-level feature subsystems SHALL be `resource`, `output`, `session`, `capture`, `search`, and `execution`, plus shared configuration, Houdini transport, target coordination, temporary-workspace, and low-level search primitives. Each feature subsystem SHALL expose a public service boundary and own its feature-specific implementation details.

#### Scenario: Search stores a Resource
- **WHEN** Search needs to preserve a code body or oversized logical result
- **THEN** Search uses the Resource service boundary
- **AND** Search does not open or mutate Resource database tables directly

#### Scenario: Execution sends Python to Houdini
- **WHEN** Execution dispatches caller-provided source
- **THEN** Execution uses the shared Houdini transport and target-coordination boundaries
- **AND** transport does not acquire feature-specific persistence responsibilities

### Requirement: Construct only the runtime required by the requested command

The CLI composition root SHALL construct only the services required by the selected command. A feature SHALL NOT require initialization of unrelated databases or feature runtimes merely to execute its own operation.

#### Scenario: Execute Python
- **WHEN** `houbridge exec` is invoked
- **THEN** the runtime constructs the execution, transport, target, Resource/output, and configuration dependencies required by that invocation
- **AND** local script-search storage is not opened solely because Execution runs

#### Scenario: Search workspace scripts
- **WHEN** `houbridge search script` is invoked
- **THEN** the workspace script-search runtime is constructed
- **AND** a Houdini connection is not required for that local-only operation

### Requirement: Keep Execution state invocation-local

Execution SHALL operate on the caller's source, invocation options, transient transport files, and produced output only for the lifetime of the invocation. Execution SHALL not require project-scoped persistent execution state.

#### Scenario: One execution completes
- **WHEN** the Houdini invocation and output collection finish
- **THEN** Execution returns the logical result to the common Output subsystem
- **AND** no project-scoped execution record is required for a later command

#### Scenario: A later execution starts
- **WHEN** another `exec` invocation begins
- **THEN** it does not require metadata from the earlier execution

### Requirement: Treat Houdini scene data as live application state

Houbridge SHALL read and modify the active Houdini scene through native Houdini APIs while keeping Houbridge persistence in the external storage scopes defined by this specification set. Scene contents SHALL not be required as Houbridge's own persistence store.

#### Scenario: Open an existing Hip file
- **WHEN** Houbridge connects to a running scene
- **THEN** Session, Capture, Search, and Execution operate on the current native Houdini state
- **AND** their operation does not depend on Houbridge persistence being present inside the scene

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

The Resource subsystem SHALL store Resource payload bytes and Resource metadata in `<current-working-directory>/.houbridge/resources.db`. No sibling Resource payload directory is required.

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
- **WHEN** a command needs a durable local inspection handle for a payload
- **THEN** that payload belongs to `<cwd>/.houbridge/resources.db`

### Requirement: Keep the global data root operational

The global Houbridge data root SHALL contain only installation/user-level operational runtime state such as locks and transient command files. Workspace Resource and script-search data SHALL use their workspace-local storage scopes.

#### Scenario: Two working directories use one installation
- **WHEN** independent workspaces use the same Houbridge installation
- **THEN** their `.houbridge/resources.db` and `.houbridge/search.db` stores remain workspace-local
- **AND** installation-level operational directories may still be shared

### Requirement: Implement only the current specification set

Implementation behavior SHALL be derived from the requirements present in the current specification set. Unspecified feature persistence, command families, metadata fields, and cross-subsystem dependencies SHALL not be inferred from older implementations.

#### Scenario: Rebuild a subsystem
- **WHEN** an implementation is replaced from these specifications
- **THEN** its public surface and persistence are taken from the current requirements
- **AND** unrelated behavior is not added without a corresponding current requirement
