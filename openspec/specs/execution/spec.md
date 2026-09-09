# Execution Feature Specification

## Purpose

Define caller-file Houdini Python execution, execution output capture, shared per-process target serialization, and the low-level execution boundary reused by synchronous Exec and asynchronous Task Runtime. Command JSON schemas are specified separately.

## Requirements

### Requirement: Execute caller-side Python files inside Houdini

Execution SHALL accept Python source read from a caller-supplied file and execute that exact source inside the selected running Houdini session using Houdini's native Python environment. Multiline source, quotes, Unicode, and other valid Python source SHALL be transported without shell re-quoting changing the source contents.

#### Scenario: Execute multiline Unicode source
- **WHEN** the supplied file contains multiple lines, quotes, or Unicode text
- **THEN** the source compiled inside Houdini is semantically identical to the file content read by Houbridge

### Requirement: Preserve the file execution namespace contract

User code SHALL execute with `__name__ == "__main__"` and SHALL expose the caller-supplied file path as `__file__`.

#### Scenario: Execute a caller-side Python file
- **WHEN** Execution is given a file source path and its already-read source
- **THEN** Houdini executes that source with `__name__` set to `__main__`
- **AND** `__file__` is set to the supplied file path

### Requirement: Support caller-file arguments without consuming them as Houbridge options

File execution SHALL support script arguments that become the executed file's `sys.argv`. `sys.argv[0]` SHALL be the supplied file path and following values SHALL be the caller's file arguments. Houdini's previous `sys.argv` SHALL be restored whether user code succeeds or raises.

#### Scenario: File receives arguments
- **WHEN** a file execution includes caller script arguments
- **THEN** user code observes the specified argv values

#### Scenario: User code raises
- **WHEN** execution temporarily changes `sys.argv` and the user source raises
- **THEN** Houdini's prior `sys.argv` is restored in the execution cleanup path

### Requirement: Capture stdout, stderr, result, and Python failure diagnostics

The low-level execution boundary SHALL be able to capture stdout, stderr, a declared `result` value, and Python exception traceback without streaming unbounded bodies directly through the public CLI response. Synchronous Exec MAY expose all of these according to its command contract. Async Task SHALL persist its defined stdout/stderr Task streams and terminal state according to the Task specification.

#### Scenario: User Python writes stdout and stderr
- **WHEN** user source produces both streams
- **THEN** they are captured independently

#### Scenario: User Python raises
- **WHEN** an exception escapes caller source
- **THEN** the traceback is captured as the Python failure diagnostic
- **AND** stdout/stderr already produced by the source remain available to the owning synchronous or Task execution path

### Requirement: Classify synchronous declared results deterministically

When a synchronous execution namespace contains `result`, Execution SHALL classify the value as follows:

- a string that parses as JSON is JSON content without double encoding,
- a string that does not parse as JSON is plain text,
- a non-string JSON-serializable value is serialized as JSON,
- a non-JSON-serializable value is represented with a bounded `reprlib` representation as plain text.

Async Task completion output is defined by the Task specification and SHALL NOT expand its completion Resource beyond the Task fields defined there.

#### Scenario: Synchronous result is a JSON string
- **WHEN** `result` is a string containing valid JSON
- **THEN** it is classified as JSON rather than JSON-encoded a second time

#### Scenario: Synchronous result is an arbitrary Python object
- **WHEN** JSON serialization fails for `result`
- **THEN** Execution returns a bounded textual representation rather than failing solely because the result object is not JSON-serializable

### Requirement: Route synchronous execution output through Resource and Output boundaries

Synchronous Execution SHALL return its logical result/stdout/stderr/failure data through the shared Resource and Output boundaries defined by their specifications. Execution SHALL not implement a separate token-limit or hard-output policy.

#### Scenario: Result fits inline policy
- **WHEN** a synchronous result is small enough for the common inline policy
- **THEN** the command contract may expose the inline value together with any required Resource reference

#### Scenario: Result exceeds inline policy
- **WHEN** a synchronous result is too large for direct CLI output
- **THEN** the complete payload remains inspectable through the Resource subsystem
- **AND** the common Output policy determines the final bounded response

### Requirement: Keep ownership of asynchronous operational state in Task

Synchronous execution state SHALL remain invocation-local. When `exec --async` is selected, queue state, the submitted source copy, Task metadata, stream chunks, runtime ownership, and retention SHALL be owned by the Task subsystem. Execution keeps only the active invocation state required by the owning synchronous or Task path.

#### Scenario: Synchronous execution completes
- **WHEN** result collection and final output construction finish
- **THEN** no persistent execution record is required for a later command

#### Scenario: Async execution is submitted
- **WHEN** Exec accepts a file for asynchronous execution
- **THEN** Execution does not create a second persistent execution record
- **AND** Task owns the operational state needed after the submitting CLI exits

### Requirement: Serialize managed execution per Houdini process

All managed Python executions directed at the same probed Houdini process id SHALL be serialized through one shared target-coordination boundary, regardless of whether the caller is synchronous Exec or Async Task. Different Houdini process ids MAY proceed independently. The per-process concurrency limit SHALL always be one.

#### Scenario: Sync and async execution target the same PID
- **WHEN** an Async Task is running against PID `1000` and a synchronous Exec targets the same PID
- **THEN** they do not execute arbitrary Python concurrently inside that process

#### Scenario: Independent processes execute
- **WHEN** managed executions target different Houdini process ids
- **THEN** the per-process serialization rule does not by itself prevent those executions from overlapping

### Requirement: Use invocation-local execution transport files

Execution MAY use a unique temporary directory and generated runnable script for transport, stream buffering, markers, and result exchange. Such files SHALL be operational invocation state rather than workspace persistence. Reusable Houdini-side implementation SHALL live below `houbridge/houdini/scripts/execution/`.

#### Scenario: Start a new synchronous execution
- **WHEN** dispatch begins
- **THEN** the invocation receives isolated temporary transport/result paths
- **AND** reusable execution logic comes from the Execution injected-script boundary

#### Scenario: Task uses stream transport files
- **WHEN** an asynchronous execution needs observable stdout/stderr while running
- **THEN** Task may use isolated invocation-local transport files through the shared temporary-workspace mechanism
- **AND** those files are not the authoritative Task output store

### Requirement: Use the selected existing Houdini openport session

Managed Execution SHALL target the selected reachable local Houdini openport through SideFX `hcommand`.

#### Scenario: Selected target is reachable
- **WHEN** the configured local openport responds
- **THEN** Execution dispatches the invocation-local Houdini script to that session

#### Scenario: Selected target is unreachable
- **WHEN** SideFX transport cannot reach the selected local openport
- **THEN** Execution reports a connection or transport failure to the owning caller

### Requirement: Separate asynchronous dispatch establishment timeout from Python run duration

Finite Houdini probe/transport timeout settings SHALL remain applicable while establishing an asynchronous dispatch and verifying that the bound target has started the invocation. The injected execution wrapper SHALL atomically publish and flush an invocation-local started marker before running caller Python, so observing caller execution implies that the recovery-visible started marker already exists. Once that started marker is observed, Async Task SHALL NOT apply a wall-clock timeout to the caller's Python execution merely because `[houdini].transport_timeout_seconds` elapsed.

Queue waiting SHALL also have no elapsed-time timeout. A running Task MAY therefore remain `running` indefinitely when caller Python does not terminate. Transport failure, bound-process disappearance, or another condition proving that managed execution cannot continue MAY terminate the Task according to the Task failure contract.

#### Scenario: Long Python execution exceeds transport timeout duration
- **WHEN** the async invocation has already published its started marker and caller Python continues beyond the configured transport timeout
- **THEN** the Task remains `running`
- **AND** it is not failed solely because that duration elapsed

#### Scenario: Async dispatch never establishes
- **WHEN** the bound target does not reach the started marker within the finite dispatch/probe timeout
- **THEN** Task reports a runtime/transport failure
- **AND** the source is not automatically re-dispatched when it may already have started

### Requirement: Surface SideFX transport failures without fabricating Python success

Non-zero `hcommand` exits and transport failures SHALL be reported as execution/transport failures. A transport failure SHALL not be converted into a successful Python result.

#### Scenario: hcommand exits non-zero during synchronous execution
- **WHEN** SideFX transport reports a non-zero exit
- **THEN** Execution reports the transport failure
- **AND** does not fabricate a successful result
