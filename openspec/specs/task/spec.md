# Async Task Feature Specification

## Purpose

Define minimal asynchronous execution state for long-running Houdini Python file execution, including queueing, runtime ownership, stdout/stderr observation, process binding, retention, and completion Resource finalization.

## Requirements

### Requirement: Persist Task operational state in one global database

Task operational state SHALL be stored in one `tasks.db` below the configured global Houbridge operational storage root. The database SHALL be shared across working directories and Houdini processes rather than split by cwd, target port, or PID.

The Task store SHALL contain enough state to represent Task metadata, appendable stdout/stderr chunks, semantic ordinal allocation, and runtime coordination. A Task SHALL retain at least its id, status, file, args, optional purpose, absolute origin root, target port, target PID, created/started/finished timestamps as applicable, completion Resource id when applicable, the submission-time History enablement decision, and runtime failure information when applicable. The origin root SHALL be the submission process current working directory resolved to an absolute path and SHALL preserve the execution's project/cwd context for later Action History finalization.

#### Scenario: Two workspaces submit Tasks
- **WHEN** Async Tasks are submitted from different current working directories
- **THEN** both Tasks are discoverable through the same global Task command surface
- **AND** their origin roots remain distinct Task metadata

#### Scenario: Different Houdini processes submit Tasks
- **WHEN** Tasks target different Houdini PIDs
- **THEN** Task persistence remains in the same global `tasks.db`

### Requirement: Use exactly four public Task states

The public Task status SHALL be exactly one of:

```text
queued
running
completed
failed
```

A newly committed Task SHALL be publicly `queued`. It SHALL become `running` only when its bound Houdini invocation has started. Successful terminal execution SHALL become `completed`; Python failure or Task Runtime failure SHALL become `failed`.

#### Scenario: Task waits for capacity
- **WHEN** a submitted Task cannot yet execute because global capacity or its bound PID is busy
- **THEN** its public status remains `queued`

#### Scenario: Bound execution starts
- **WHEN** the Houdini-side started marker for the Task invocation is observed
- **THEN** the public status becomes `running`

### Requirement: Freeze submitted source for queued execution

Async submission SHALL read the Python file before Task creation. The exact submitted source SHALL be stored as Task-owned operational payload while it is required to execute or recover the queued/running Task. The Task Runtime SHALL execute that submitted source copy rather than re-reading a potentially modified file later.

The source body SHALL be removed from Task persistence after the Task reaches `completed` or `failed`. The file path and arguments MAY remain until Task retention expires.

#### Scenario: File changes while Task is queued
- **WHEN** the caller edits the source file after Task submission but before execution begins
- **THEN** the Task executes the submitted source copy captured at submission
- **AND** its semantic Task id continues to describe the submitted source rather than the later file contents

#### Scenario: Task reaches a terminal state
- **WHEN** Task finalization completes as `completed` or `failed`
- **THEN** the stored Python source body is removed from Task persistence

### Requirement: Generate Task ids from submitted Python source

Task SHALL use the shared semantic base generator over the submitted Python source body. File name and script arguments SHALL NOT participate in semantic base generation. Normal semantic generation SHALL use the shared three-tag semantics, followed by a Task-owned ordinal local to the resulting semantic base.

Examples include:

```text
geometry-build-cache-000
geometry-build-cache-001
render-camera-preview-000
```

The ordinal SHALL have minimum width three and SHALL expand naturally beyond `999`.

#### Scenario: Two Tasks share a semantic base
- **WHEN** two submitted sources resolve to semantic base `geometry-build-cache`
- **THEN** they receive distinct increasing Task ordinals such as `000` and `001`

#### Scenario: Script arguments differ
- **WHEN** two submissions use the same source body with different arguments
- **THEN** arguments do not alter the semantic base
- **AND** ordinal allocation still distinguishes the Task ids

### Requirement: Keep semantic fallback caller-owned

The shared semantic base generator SHALL accept a caller-supplied fallback stem and SHALL NOT hard-code Task, Resource, or another feature name into generic generation logic. Task SHALL supply fallback stem `task-unknown` when the defined semantic fallback condition is reached.

#### Scenario: Task semantic generation reaches the defined fallback condition
- **WHEN** a meaningful normal semantic base cannot be produced under the shared fallback rule
- **THEN** Task supplies `task-unknown`
- **AND** Task ordinal allocation can produce `task-unknown-000`

### Requirement: Allocate Task ordinals independently from retained Task rows

`tasks.db` SHALL keep semantic ordinal state independently from the Task rows subject to retention cleanup. Deleting expired `completed` or `failed` Tasks SHALL NOT make their ordinals reusable. Task ordinal allocation SHALL be atomic under concurrent submissions.

Only a successful Task reset SHALL clear Task semantic ordinal state so that allocation can begin again from `000`.

#### Scenario: Old Tasks expire
- **WHEN** Tasks `geometry-build-cache-000` through `002` have been removed by retention
- **THEN** the next Task for that semantic base does not reuse `000`, `001`, or `002`

#### Scenario: Concurrent submissions share one base
- **WHEN** multiple submitters allocate the same semantic base concurrently
- **THEN** each receives a distinct ordinal

### Requirement: Drive queued Tasks through an on-demand background runtime

A successful async submission SHALL be processed by an on-demand Houbridge Task Runtime that can continue after the submitting CLI process exits. The runtime SHALL coordinate through global Task operational state and MAY exit when no Task is running and no queued Task remains.

After a Task reaches a terminal state, the runtime SHALL check for executable queued work before retiring. If another Task is available, processing SHALL continue without requiring a new long-lived daemon. Submission and runtime retirement SHALL be coordinated so that a Task committed during the retirement boundary is either observed by the current runtime or causes a runtime to become active.

#### Scenario: Another Task is queued at completion
- **WHEN** Task A finishes and Task B is queued and executable
- **THEN** the active Task Runtime continues and may claim Task B
- **AND** it does not retire merely because Task A ended

#### Scenario: Queue becomes empty
- **WHEN** no Task is running and no queued Task remains
- **THEN** the on-demand Task Runtime may retire

#### Scenario: Submission races with retirement
- **WHEN** a new Task is committed while the current runtime is retiring
- **THEN** coordination guarantees that some active/recoverable runtime owns the queued work
- **AND** the Task is not stranded solely by that race

### Requirement: Limit Async Task concurrency globally and per Houdini process

Task Runtime SHALL enforce `[task].max_concurrency` as the maximum number of concurrently `running` Async Tasks across Houbridge. The value SHALL be at least `1`; the generated default SHALL be `1`. This global count SHALL apply to Async Tasks only. Slot/claim accounting SHALL be coordinated through shared Task operational state so multiple runtime processes cannot each enforce only a process-local limit and collectively exceed the configured global maximum.

Regardless of the configured global value, arbitrary managed Python execution concurrency per probed Houdini PID SHALL always be `1`, using the shared target-coordination boundary also used by synchronous Exec. A synchronous Exec SHALL not consume an Async Task global slot, but it SHALL still serialize against an Async Task targeting the same Houdini PID.

#### Scenario: Default concurrency is used
- **WHEN** `[task].max_concurrency = 1`
- **THEN** at most one Async Task is running globally

#### Scenario: Higher global concurrency uses different PIDs
- **WHEN** `[task].max_concurrency = 3` and executable queued Tasks target PIDs `1000`, `2000`, and `3000`
- **THEN** up to three Async Tasks may run concurrently

#### Scenario: Multiple queued Tasks target one PID
- **WHEN** multiple Tasks target PID `1000`
- **THEN** at most one of those Tasks runs at a time even when global capacity is greater than one

#### Scenario: Sync Exec overlaps another PID
- **WHEN** an Async Task runs against PID `1000` and synchronous Exec targets PID `2000`
- **THEN** the Task global concurrency setting does not block the synchronous Exec

### Requirement: Bind each Task to the Houdini process selected at submission

Async submission SHALL probe the selected local Houdini target and record its target port and operating-system PID. Before dispatch, Task Runtime SHALL probe the bound port again and SHALL execute only if it still resolves to the recorded PID. A changed process SHALL not receive source submitted for the previous process.

Target PID and port are internal Task execution metadata and need not be exposed by the public Task JSON contract.

#### Scenario: Houdini is restarted before queued execution
- **WHEN** a Task was submitted for PID `1000` and the same port later resolves to PID `2000`
- **THEN** the Task becomes `failed`
- **AND** its source is not executed in PID `2000`
- **AND** runtime failure information identifies the target change

### Requirement: Persist Task stdout and stderr incrementally in tasks.db

The authoritative Task stdout/stderr SHALL be appendable data in `tasks.db`, not one repeatedly rewritten monolithic Task field. Internal output chunks MAY be represented with sequence numbers and stream identity such as `stdout` and `stderr`; chunk structure SHALL remain private to the Task subsystem.

Invocation-local temporary files MAY be used as transport buffers between Houdini execution and Task Runtime. Paths/markers needed to recover an active invocation MAY be retained as private Task runtime metadata while the Task is active. Task Runtime SHALL copy newly flushed stream content into `tasks.db` while the Task is running and SHALL remove invocation-local stream buffers after terminal output has been committed and they are no longer required for recovery.

Houbridge SHALL treat stdout/stderr as ordinary Python streams. It SHALL NOT define a progress API, percentage parser, ANSI terminal emulator, carriage-return protocol, or print-event protocol.

#### Scenario: Caller flushes stdout during execution
- **WHEN** Python executes `print("20%", flush=True)` while the Task is running
- **THEN** Task Runtime makes that flushed text observable through subsequent `task get`
- **AND** Houbridge does not interpret `20%` as structured progress

#### Scenario: Output contains many chunks
- **WHEN** a long-running Task produces output repeatedly
- **THEN** new chunks are appended without rewriting the complete accumulated stream for every write

### Requirement: Return accumulated streams as logical Task state

Task read operations SHALL reconstruct stdout and stderr in sequence order and expose the complete accumulated text available at the time of the read. Task SHALL not expose output chunk ids, cursors, consumed offsets, or a differential-read protocol.

The logical Task response SHALL then pass through the common Output Policy, so very large Task-get results may use normal whole-result Resource fallback without changing Task's full-stream logical contract.

#### Scenario: Read a running Task twice
- **WHEN** the first read observes `10%\n` and later output appends `20%\n`
- **THEN** the second logical read exposes `10%\n20%\n`
- **AND** no cursor from the first read is required

### Requirement: Distinguish Python failure from Task Runtime failure

A Python exception SHALL make the Task `failed` while preserving the traceback in the Task stderr stream. Houbridge/Task Runtime failures SHALL be represented separately as structured runtime failure information with a stable code and message, without injecting that diagnostic into the caller's stderr stream.

#### Scenario: Caller Python raises
- **WHEN** an exception escapes the submitted source
- **THEN** Task status becomes `failed`
- **AND** the Python traceback remains in `stderr`

#### Scenario: Bound target changes
- **WHEN** runtime detects that the submitted target PID has changed
- **THEN** Task status becomes `failed`
- **AND** Task runtime failure information uses code `task_target_changed`
- **AND** caller stderr is not fabricated from that Houbridge diagnostic

### Requirement: Do not automatically replay a possibly-started Task

Task Runtime SHALL NOT automatically re-dispatch submitted Python when there is evidence that the invocation may already have started. Invocation-local started/completion markers and Task runtime ownership metadata SHALL allow a replacement runtime to distinguish queued work that is safe to claim from started work that must not be replayed. The completion marker SHALL be published only after the execution wrapper has captured the Python outcome and flushed the Task stdout/stderr transport streams; it SHALL be published for both successful completion and Python failure.

If a replacement runtime observes a started Task without a completion marker while the bound Houdini PID is still valid, it SHALL monitor/finalize that existing invocation rather than submit the source again. If the bound process is no longer valid, the Task SHALL become `failed`.

#### Scenario: Task Runtime exits after Python started
- **WHEN** another Task Runtime later recovers ownership and the started marker exists
- **THEN** it does not execute the submitted source a second time

#### Scenario: Completion marker exists after runtime restart
- **WHEN** caller Python already finished and the completion marker is available
- **THEN** replacement runtime may continue output/resource finalization for that same invocation

#### Scenario: Python fails before runtime restart
- **WHEN** caller Python raised, its traceback streams were flushed, and the completion marker records the finished invocation
- **THEN** replacement runtime finalizes that same Task as `failed`
- **AND** it does not execute the source again

### Requirement: Carry History context through asynchronous execution

Async submission SHALL capture the optional `purpose`, absolute origin root, file, args, source hash/source body, and the effective `[history].enabled` decision needed to finalize the same Action History semantics as synchronous Execution. Task Runtime SHALL start Action Change recording only when the queued Python invocation actually starts and History was enabled for that submission. Queue wait and Task runtime bookkeeping SHALL not create History entries by themselves.

When a started invocation reaches a normal Python terminal outcome, Task Runtime SHALL offer the finalized execution context and Action Change set to the History service. A Python exception SHALL produce a `failed` History action when the session History can be finalized. History persistence failure SHALL not cause the caller Python to be replayed or change a successfully determined Python outcome.

#### Scenario: Async execution was submitted with purpose
- **WHEN** `exec --async --purpose "build preview geometry"` later starts in Houdini
- **THEN** Task Runtime supplies that purpose and the captured origin root to History finalization

#### Scenario: Task remains queued
- **WHEN** a Task has not yet started caller Python
- **THEN** no Action History entry exists solely for its queued state

#### Scenario: Enabled History preflight fails before Task start
- **WHEN** Task Runtime cannot prepare the required session History store, source embedding, or Action baseline
- **THEN** caller Python does not start
- **AND** the Task becomes `failed` through its runtime-failure contract

#### Scenario: Python raises after starting
- **WHEN** caller Python starts with History enabled and later raises while the Houdini session remains finalizable
- **THEN** History receives a `failed` action entry with the observed Action Changes
- **AND** Task stderr retains the Python traceback according to the Task stream contract

### Requirement: Finalize successful Task output as one global Resource

After successful Python completion and final stdout/stderr collection, Task SHALL create one immutable JSON Resource in `resources.db` under the same effective global operational root as its `tasks.db`. The Resource payload SHALL contain exactly:

```json
{"stdout":"...","stderr":"..."}
```

Task file path, arguments, purpose, id, timestamps, PID, origin root, and other Task metadata SHALL NOT be duplicated into this completion Resource. Resource creation SHALL complete before Task status is committed as `completed`. The terminal Task SHALL retain the Resource id; Resource resolution uses the Task command's effective global operational root rather than the Task origin cwd.

#### Scenario: Task completes successfully
- **WHEN** Python exits successfully and stream collection is complete
- **THEN** the stdout/stderr JSON Resource is created in global `resources.db`
- **AND** only after successful Resource creation does Task become `completed`

#### Scenario: Resource finalization fails
- **WHEN** the completion Resource cannot be created
- **THEN** Task is not reported as `completed`
- **AND** Task becomes `failed` with Task Runtime failure information
- **AND** its collected stdout/stderr remain available in Task state

#### Scenario: Runtime exits after Resource creation but before Task commit
- **WHEN** the immutable completion Resource was created but Task status was not yet committed as `completed`
- **THEN** replacement finalization may store the same exact completion payload again
- **AND** Resource content addressing resolves it to the same canonical payload
- **AND** Task may then commit the resulting Resource reference and `completed` state

### Requirement: Retain terminal Tasks for the Resource TTL duration

Task SHALL use the effective `[resource].ttl_hours` retention duration and SHALL NOT define a separate Task TTL setting. The generated Resource TTL is 72 hours. `queued` and `running` Tasks SHALL not expire due to TTL. A `completed` or `failed` Task becomes eligible for removal only after its `finished` time plus the effective Resource TTL.

Task reads SHALL NOT extend retention. Task source has already been removed at terminal state even while terminal metadata and output remain retained. Task semantic ordinal state SHALL survive ordinary retention cleanup.

#### Scenario: Running Task exceeds 72 hours
- **WHEN** caller Python remains running longer than the configured Resource TTL
- **THEN** the Task is not removed merely because that duration elapsed

#### Scenario: Completed Task ages past retention
- **WHEN** a terminal Task is older than its finished-time retention deadline
- **THEN** its Task row and Task output may be removed
- **AND** its semantic ordinal allocation remains reserved until Task reset

### Requirement: Reset Task subsystem only when no active Task exists

Task reset SHALL be allowed only when no `queued` or `running` Task exists. The active-state check and reset SHALL be coordinated atomically with Task submission/claiming. A successful reset SHALL clear retained `completed`/`failed` Task metadata, Task stdout/stderr, and Task semantic ordinal state. It SHALL NOT delete Resources previously created by Tasks.

#### Scenario: Reset after every Task is terminal
- **WHEN** no `queued` or `running` Task exists
- **THEN** Task reset clears terminal Task state and semantic ordinal state
- **AND** future Task ordinals may begin again at `000`
- **AND** previously created Resources remain unchanged

#### Scenario: Reset while work is active
- **WHEN** at least one Task is `queued` or `running`
- **THEN** reset fails through the common BridgeError envelope
- **AND** Task state is not partially reset
