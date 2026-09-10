# Session Action History Feature Specification

## Purpose

Define a minimal, session-scoped Action History that lets AI callers recall managed Python actions performed in the currently running Houdini process. History stores execution context, source-code embeddings, and compact Before/After Action Changes for recall and search.

## Requirements

### Requirement: Scope one History database to one Houdini process incarnation

History SHALL store one `history.db` per active Houdini process incarnation below the effective global operational root:

```text
<global-root>/history/<session-key>/history.db
```

`<session-key>` SHALL be derived from the probed Houdini operating-system PID together with an operating-system process-start identity or equivalent process-incarnation value. The session key SHALL not require a persistent scene identifier. History commands SHALL probe the selected Houdini target and resolve only the database belonging to that exact live process incarnation.

#### Scenario: Two Houdini processes are active
- **WHEN** Houdini PIDs `1000` and `2000` are both reachable
- **THEN** their Action History databases resolve to distinct session directories

#### Scenario: A PID is reused by the operating system
- **WHEN** a later Houdini process receives a PID previously used by an earlier process
- **THEN** its process-start identity produces a different session key
- **AND** the earlier History database is not treated as the new process's History

### Requirement: Use Houdini node session ids inside one session History

Action History SHALL identify tracked Houdini nodes with the integer `hou.Node.sessionId()` value obtained in the owning Houdini process. Node session ids SHALL be interpreted only within the History database selected for that process incarnation. Stored paths SHALL provide human-readable context but SHALL not replace session-local node identity.

#### Scenario: A node is renamed
- **WHEN** a tracked node changes path during one execution
- **THEN** its Action Changes continue to use the same node session id
- **AND** Before/After path information describes the rename

### Requirement: Make Action History recording configurable and enabled by default

The generated configuration SHALL use `[history].enabled = true`. The effective setting for an Exec submission SHALL determine whether that execution initializes Action Change capture and contributes a History entry. Disabling History SHALL skip Action recorder setup, History source embedding work, and History entry creation for that invocation.

History read commands MAY inspect an already-existing current-session database regardless of whether recording is disabled for the caller's current working directory.

#### Scenario: Recording is enabled
- **WHEN** managed Python actually starts with effective `[history].enabled = true`
- **THEN** the execution is eligible for Action History finalization

#### Scenario: Recording is disabled
- **WHEN** managed Python runs with effective `[history].enabled = false`
- **THEN** its execution proceeds without History capture or History embedding work

### Requirement: Persist one minimal entry per finalized started execution

A finalized Action History entry SHALL contain:

- session-local monotonic integer `id`,
- execution start `time`,
- absolute origin `root` representing the Exec submission cwd,
- terminal Python `status` of `completed` or `failed`,
- executed `file` path,
- script `args`,
- optional caller-supplied `purpose`,
- SHA-256 `source_hash` of the exact executed Python source,
- zero or more finalized Action Changes.

The Python source body SHALL be used transiently for hashing and embedding but SHALL not be persisted as History source text. Result payloads and stdout/stderr remain owned by Execution, Task, Resource, and Output according to their specifications rather than being copied into the Action History entry.

#### Scenario: Synchronous execution completes
- **WHEN** caller Python starts and exits successfully with History enabled
- **THEN** one `completed` History entry is committed for that execution

#### Scenario: Caller Python raises
- **WHEN** caller Python starts and its wrapper reaches a final Python-exception outcome while the session remains finalizable
- **THEN** one `failed` History entry is committed with Action Changes observed for that execution

#### Scenario: Caller Python never starts
- **WHEN** file validation, target probing, or dispatch establishment fails before caller source starts
- **THEN** no Action History entry is created for that attempt

### Requirement: Allocate History ids monotonically within the session

History entry ids SHALL be monotonically increasing integers local to one session History database. An id SHALL remain sufficient to address an entry only in conjunction with the currently selected Houdini session database.

#### Scenario: Three actions are recorded
- **WHEN** the current session commits three entries in order
- **THEN** their ids increase monotonically within that History database

### Requirement: Store source embeddings without storing source bodies

History SHALL embed the exact executed Python source with the session History code embedding profile and SHALL persist the vector keyed by `source_hash` and profile. Multiple History entries that execute identical source under the same profile SHALL reuse the stored embedding rather than duplicate it.

When a session History database is first initialized, it SHALL record the effective `[search.embedding].code_profile` as that session History's code embedding profile. Subsequent History writes and History semantic searches for that process incarnation SHALL use the profile recorded by the session database, even if a later cwd-local configuration specifies a different code profile. This keeps all vectors in one session History comparable.

#### Scenario: Same source executes twice
- **WHEN** two History entries have the same exact Python source hash
- **THEN** both entries may reference one stored code embedding for that hash/profile

#### Scenario: Local embedding configuration later changes
- **WHEN** the session History was initialized with profile A and a later invocation's local configuration requests profile B
- **THEN** History embedding/search for that existing session continues to use profile A
- **AND** workspace script search may still use its own effective configuration independently

### Requirement: Capture a lightweight in-memory Action baseline around caller Python

When History is enabled, the Houdini-side Action recorder SHALL establish an invocation-local baseline immediately before caller Python starts. The baseline SHALL contain only state required by the tracked Action Change types: node session id, node path/type, parameter raw values, and input-connection identity. The baseline SHALL remain invocation-local and SHALL be discarded after History finalization.

History SHALL use Houdini node event callbacks to identify changed nodes/properties during the execution window. The recorder SHALL handle `ParmTupleChanged` callbacks whose `parm_tuple` argument is `None` by comparing the affected node against its baseline/current raw parameter state.

#### Scenario: No tracked state changes
- **WHEN** caller Python runs without changing any tracked node/property
- **THEN** the finalized History entry contains an empty Action Change list

#### Scenario: Many parameters change in one Houdini callback
- **WHEN** Houdini reports `ParmTupleChanged` with no individual parameter tuple
- **THEN** the recorder compares raw parameter state for that affected node
- **AND** records the parameters whose Before/After states differ

#### Scenario: A newly created node changes again in the same execution
- **WHEN** `ChildCreated` introduces a node and caller Python subsequently renames, rewires, or changes parameters on that node
- **THEN** the Action recorder tracks the new node for the remainder of the execution window
- **AND** later tracked changes can reference the same node session id

### Requirement: Record exactly five Action Change types

The finalized Action Change vocabulary SHALL be exactly:

```text
node_created
node_deleted
node_renamed
parm_changed
input_rewired
```

Each change SHALL preserve a Before/After description sufficient for AI recall. Node creation SHALL use `before: null`; node deletion SHALL use `after: null`. Rename, parameter, and input changes SHALL preserve both states.

#### Scenario: Node is created
- **WHEN** `ChildCreated` identifies a new node during caller Python
- **THEN** History records `node_created` using that node's session id and its created path/type as the After state

#### Scenario: Node is deleted
- **WHEN** `ChildDeleted` identifies a node before deletion
- **THEN** History records `node_deleted` using the node's session id and its path/type as the Before state

#### Scenario: Node is renamed
- **WHEN** `NameChanged` occurs during caller Python
- **THEN** History records `node_renamed` with the prior and resulting node paths

#### Scenario: Input is changed
- **WHEN** `InputRewired` occurs for an input index
- **THEN** History records the previous and resulting upstream connection identity for that input

### Requirement: Store parameter changes as unevaluated raw values

A `parm_changed` Action Change SHALL identify the node session id, current node path, parameter name, and string Before/After states obtained from Houdini raw parameter values without evaluating expressions or expanding variables. The recorder SHALL compare individual `hou.Parm` components so a changed tuple can be represented by the component parameter names that actually differ.

#### Scenario: Expression parameter changes
- **WHEN** a parameter raw value changes from `$HIP/a.$F.bgeo` to `$HIP/b.$F.bgeo`
- **THEN** History stores those raw strings as Before/After
- **AND** does not replace them with frame-expanded filesystem paths

### Requirement: Keep Action History persistence session-local and database-complete

Each session `history.db` SHALL contain the History entries, Action Changes, source embedding cache, lexical-search state, vector-search state, and session metadata required by History. History SHALL not require another feature database to reconstruct a `history get` result or rank a current-session History search, except for shared configuration/model loading and live-session selection.

#### Scenario: Read one recorded action
- **WHEN** `history get` resolves an id in the current session database
- **THEN** file, args, purpose when present, root, status, time, and Action Changes are read from that session History database

### Requirement: Search source semantics and lexical action context through shared primitives

History search SHALL use the shared low-level search primitives. The dense branch SHALL compare the query embedding against stored executed-source embeddings only. The lexical branch SHALL use FTS5/BM25 over a deterministic textual projection of `purpose`, `file`, `args`, and Action Change context including change type, node path/type, parameter name, connection path, and serializable Before/After values. Action Change text SHALL not be embedded as an additional semantic document.

History SHALL combine the available dense and lexical candidate rankings with the configured reciprocal-rank-fusion primitive; an empty branch does not prevent the non-empty branch from contributing through the same RRF path. Public History search scores SHALL therefore use the shared RRF score formatter.

#### Scenario: Query resembles previously executed code
- **WHEN** query semantics are close to a stored executed-source embedding
- **THEN** the dense branch can rank that History entry even though the source body is not stored

#### Scenario: Query names a changed parameter
- **WHEN** a query lexically matches a stored parameter name or node path
- **THEN** the lexical branch can rank the corresponding History entry

#### Scenario: History search returns a score
- **WHEN** one or both retrieval branches produce candidates
- **THEN** the final ranked candidates pass through RRF
- **AND** the public score uses the shared RRF score formatting rule

### Requirement: Establish enabled History before Python starts and never replay after start

When History is enabled for an invocation, the source embedding, session History store/profile, and invocation Action baseline required for recording SHALL be established before caller Python starts. A failure in this pre-start History setup SHALL fail the dispatch before caller source executes.

Once caller Python has started, a later failure to finalize or persist History SHALL not cause Houbridge to replay caller Python and SHALL not redefine an already determined Python success/failure outcome. History command failures against History persistence SHALL use normal command error handling.

#### Scenario: History preflight fails
- **WHEN** History is enabled but the session store, source embedding, or Action baseline cannot be prepared
- **THEN** caller Python does not start
- **AND** the owning synchronous Exec or Async Task reports its normal pre-start/runtime failure path

#### Scenario: History commit fails after Python succeeded
- **WHEN** caller Python has successfully completed but History finalization fails
- **THEN** the Python execution remains successful
- **AND** Houbridge does not retry the caller source solely to recover History

### Requirement: Retire History with the owning Houdini process incarnation

A session History database SHALL be considered valid for recall only while its exact Houdini process incarnation is the selected live session. When that process is no longer valid, its History directory SHALL be treated as stale. Houbridge SHALL perform lazy stale-session cleanup during later startup/session-probe opportunities; normal Session-managed shutdown MAY also request best-effort cleanup.

#### Scenario: Houdini process exits unexpectedly
- **WHEN** its History directory remains on disk
- **THEN** a later process with another incarnation does not expose that stale History as current
- **AND** Houbridge may delete the stale directory during lazy cleanup

#### Scenario: Current History database is absent
- **WHEN** the selected live session has no recorded History yet
- **THEN** History list/search can represent an empty current-session history without creating fabricated entries
