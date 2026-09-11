# Session Action History Feature Specification

## Purpose

Define a minimal, session-scoped Action History that lets AI callers recall managed Python actions performed in the currently running Houdini process. History stores execution context, source-code embeddings, and compact Before/After Action Changes for recall and search.

## Requirements

### Requirement: Scope one History database to one Houdini process incarnation

History SHALL store one `history.db` per active Houdini process incarnation below the configured global data directory:

```text
<data-dir>/history/<session-key>/history.db
```

`<session-key>` SHALL be derived from the probed Houdini operating-system PID together with an operating-system process-start identity or equivalent process-incarnation value. The session key SHALL not require a persistent scene identifier. History commands SHALL probe the selected Houdini target and resolve only the database belonging to that exact live process incarnation.

#### Scenario: Two Houdini processes are active
- **WHEN** Houdini PIDs `1000` and `2000` are both reachable
- **THEN** their Action History databases resolve to distinct session directories

#### Scenario: A PID is reused by the operating system
- **WHEN** a later Houdini process receives a PID previously used by an earlier process
- **THEN** its process-start identity produces a different session key
- **AND** the earlier History database is not treated as the new process's History

### Requirement: Destroy current History when Houdini replaces the scene

Within one live Houdini process incarnation, a successful scene replacement SHALL terminate the current Action History lifetime. Houbridge SHALL destroy the current process-incarnation History database after Houdini reports `hou.hipFileEventType.AfterLoad` or `hou.hipFileEventType.AfterClear`. History reads SHALL then observe an empty current History until new entries are recorded, and the next History-enabled execution SHALL initialize a fresh History database as needed. This reset SHALL NOT require or persist a scene UUID or other persistent scene identifier.

`AfterMerge`, Save, and Save As SHALL NOT reset History because they do not replace the current scene. A load attempt that does not reach `AfterLoad` SHALL NOT destroy the existing History solely because a load was attempted.

If `AfterLoad` or `AfterClear` occurs while a managed Python invocation is recording History, that invocation's in-memory Action baseline and pending History entry SHALL be discarded. Houbridge SHALL NOT compare state captured before the scene replacement with the replacement scene or commit that invocation's History entry after the boundary.

#### Scenario: Another HIP file is opened successfully
- **WHEN** Houdini reports `AfterLoad` for a successfully loaded scene
- **THEN** the previous scene's History database is destroyed
- **AND** History list/search for that live process observes an empty current History until new actions are recorded

#### Scenario: File New clears the current scene
- **WHEN** Houdini reports `AfterClear` after the current scene is cleared
- **THEN** the previous scene's History database is destroyed
- **AND** subsequent recorded actions belong only to the new empty scene

#### Scenario: Another HIP file is merged
- **WHEN** Houdini reports `AfterMerge`
- **THEN** the current History remains intact

#### Scenario: The current HIP file is saved
- **WHEN** the current scene is saved or saved under another path
- **THEN** the current History remains intact

#### Scenario: Scene replacement occurs during managed Python
- **WHEN** an invocation with History enabled causes or observes `AfterLoad` or `AfterClear` after caller Python has started
- **THEN** its pre-replacement Action baseline and pending History entry are discarded
- **AND** no Action Changes are finalized across the scene boundary

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
- absolute `cwd` representing the Exec submission working directory,
- terminal Python `status` of `completed` or `failed`,
- normalized absolute executed `file` path,
- script `args`,
- optional caller-supplied `purpose`,
- SHA-256 `source_hash` of the exact executed Python source,
- zero or more finalized Action Changes.

The executed file path SHALL be normalized to an absolute path before the History entry is committed so actions remain unambiguous when one Houdini session is operated from multiple working directories. The Python source body SHALL be used transiently for hashing and embedding but SHALL not be persisted as History source text. Result payloads and stdout/stderr remain owned by Execution, Task, Resource, and Output according to their specifications rather than being copied into the Action History entry.

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

When History is enabled, the Houdini-side Action recorder SHALL establish an invocation-local baseline immediately before caller Python starts. The baseline SHALL contain only state required by the tracked Action Change types: node session id, node path/type, parameter raw values, input-connection identity, and supported node flag values. The baseline SHALL remain invocation-local and SHALL be discarded after History finalization.

History SHALL use Houdini node event callbacks including creation/deletion, rename, parameter, input-rewire, and flag-change notifications to identify changed nodes/properties during the execution window. The recorder SHALL handle `ParmTupleChanged` callbacks whose `parm_tuple` argument is `None` by comparing the affected node against its baseline/current raw parameter state.

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

### Requirement: Record exactly six net Action Change types

The finalized Action Change vocabulary SHALL be exactly:

```text
node_created
node_deleted
node_renamed
parm_changed
input_rewired
flag_changed
```

History SHALL store execution-level net state change, not every intermediate Houdini callback. Existing nodes SHALL be compared from execution-start baseline to execution-end state. Multiple changes to the same tracked property SHALL compact to one Before/After change, and a property that returns to its original value SHALL produce no change.

A node created and deleted within the same execution SHALL produce no final Action Change. A newly created node that still exists at execution end SHALL produce `node_created` using its final path/type. For that surviving new node, parameter/input/flag changes from the earliest captured post-creation baseline to final state SHALL also be retained when non-zero; a separate `node_renamed` SHALL not be emitted because `node_created` already carries the final path. An existing node deleted during the execution SHALL produce `node_deleted`, and intermediate rename/parameter/input/flag changes for that deleted node SHALL not be retained. For a surviving renamed node, human-readable paths on its other changes SHALL use the final path while node session id remains the identity.

#### Scenario: Parameter changes several times
- **WHEN** one parameter changes from raw value `1` to `2` to `3` during one execution
- **THEN** History stores one `parm_changed` from `1` to `3`

#### Scenario: Parameter returns to original value
- **WHEN** one parameter changes from `1` to `2` and back to `1` before execution ends
- **THEN** no `parm_changed` is stored for that parameter

#### Scenario: New node is created and deleted
- **WHEN** caller Python creates a node and deletes it before the execution ends
- **THEN** no final Action Change for that transient node is stored

#### Scenario: Existing node is deleted after intermediate edits
- **WHEN** an existing node is renamed or edited and then deleted before execution ends
- **THEN** History retains `node_deleted` for that node
- **AND** drops its intermediate rename/parameter/input/flag changes

#### Scenario: Node flag changes
- **WHEN** one of `bypass`, `display`, `render`, `template`, or `selectable_template` is available for a node and has a different value at execution end than at baseline
- **THEN** History records one `flag_changed` with boolean Before/After values

### Requirement: Store parameter changes as bounded unevaluated raw values

A `parm_changed` Action Change SHALL identify the node session id, final node path, parameter name, and string Before/After states obtained from Houdini raw parameter values without evaluating expressions or expanding variables. The recorder SHALL compare individual `hou.Parm` components so a changed tuple can be represented by the component parameter names that actually differ.

Each Before/After raw string SHALL be encoded as UTF-8 for size accounting. Values of at most 4096 bytes SHALL be stored inline as strings. A value larger than 4096 bytes SHALL not be copied into History; instead the exact raw string SHALL be stored as a normal `text/plain` Resource in the configured global `resources.db`, and the History value SHALL be the object `{"omitted":true,"resource":"<resource-id>","tokens":<estimated-tokens>}`. `tokens` SHALL use the shared Resource/Output token estimator. The Resource obeys normal Resource retention; History does not extend that Resource's TTL.

#### Scenario: Expression parameter changes
- **WHEN** a parameter raw value changes from `$HIP/a.$F.bgeo` to `$HIP/b.$F.bgeo`
- **THEN** History stores those raw strings as Before/After
- **AND** does not replace them with frame-expanded filesystem paths

#### Scenario: Large raw parameter value changes
- **WHEN** one Before or After raw string exceeds 4096 UTF-8 bytes
- **THEN** that exact string is materialized as a `text/plain` Resource
- **AND** the History change stores `omitted:true`, the Resource id, and estimated token count instead of the large string

#### Scenario: Only one side is large
- **WHEN** one side fits inline and the other exceeds 4096 UTF-8 bytes
- **THEN** the small side remains a string
- **AND** only the large side uses the omitted Resource-reference object

### Requirement: Keep Action History persistence session-local and database-complete

Each session `history.db` SHALL contain the History entries, Action Changes, source embedding cache, lexical-search state, vector-search state, and session metadata required by History. History SHALL not require another feature database to reconstruct a `history get` result or rank a current-session History search, except for shared configuration/model loading and live-session selection.

#### Scenario: Read one recorded action
- **WHEN** `history get` resolves an id in the current session database
- **THEN** file, args, purpose when present, cwd, status, time, and Action Changes are read from that session History database

### Requirement: Search source semantics and lexical action context through shared primitives

History search SHALL use the shared low-level search primitives. The dense branch SHALL compare the query embedding against stored executed-source embeddings only. The lexical branch SHALL use FTS5/BM25 over a deterministic textual projection of `cwd`, `purpose`, `file`, `args`, and Action Change context including change type, node path/type, parameter name, connection path, and serializable inline Before/After values. Omitted large parameter bodies SHALL not be copied back into History FTS from their Resource payload; the lexical projection may include only the omission marker and bounded metadata already stored in History. Action Change text SHALL not be embedded as an additional semantic document.

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
