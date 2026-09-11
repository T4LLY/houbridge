# Exec Command Specification

## Purpose

Define the public syntax, options, and JSON response contract for executing a caller-side Python file inside the selected local Houdini session, either synchronously or as an asynchronous Task.

## Requirements

### Requirement: Execute exactly one caller-side Python file

The command syntax SHALL be:

```text
houbridge exec --file PATH [--purpose TEXT] [--async] [--session INTEGER] [-- SCRIPT_ARGS...]
```

`--file` is required. Houbridge SHALL read the file using Python source-encoding rules compatible with `tokenize.open()` before dispatch. After decoding, source containing an actual NUL character (`U+0000`) SHALL be rejected with BridgeError code `invalid_python_source` before synchronous dispatch or asynchronous Task creation. Arguments after `--` SHALL become the executed file's arguments. Async Task metadata SHALL store the normalized absolute file path even when the caller supplied a relative path.

| Option | Constraint | Default / behavior |
| --- | --- | --- |
| `--file PATH` | required readable file path | Python source read on the Houbridge side. |
| `--purpose TEXT` | optional text | Human/AI-supplied purpose recorded with enabled session Action History. |
| `--async` | boolean flag | Submit the file as an asynchronous Task instead of waiting for Python completion. |
| `--session INTEGER` | positive registered session number | Select this session instead of the registry primary. |

#### Scenario: Execute a file synchronously
- **WHEN** `houbridge exec --file tool.py` is invoked without `--async`
- **THEN** Houbridge reads `tool.py` using Python source-encoding rules
- **AND** waits for that Python execution to complete before returning its execution result

#### Scenario: Execute a file with script arguments
- **WHEN** `houbridge exec --file tool.py -- one two` is invoked
- **THEN** Houdini receives `sys.argv` equivalent to `[<supplied-file-path>, "one", "two"]`

#### Scenario: Submit a file asynchronously
- **WHEN** `houbridge exec --file tool.py --async -- --quality high` is invoked
- **THEN** the exact source read for submission is used to create the Task
- **AND** the Task stores the normalized absolute path of `tool.py`
- **AND** `--quality` and `high` are stored as Task arguments
- **AND** submission freezes the resolved dispatch context required for later Task Runtime execution, including the selected session number, resolved target port, PID/process incarnation, and required transport executable/environment/settings

#### Scenario: Supply execution purpose
- **WHEN** `houbridge exec --file tool.py --purpose "build preview geometry"` is invoked
- **THEN** the purpose is available to enabled Action History for that execution
- **AND** it is not injected into the caller script's `sys.argv`

#### Scenario: Source contains a NUL character
- **WHEN** the decoded Python file contains `U+0000`
- **THEN** Exec fails with `invalid_python_source` before caller Python is dispatched or an Async Task is created
- **AND** no Action History entry is created for that rejected source

### Requirement: Return only the Task reference for successful asynchronous submission

When `--async` is supplied, successful submission SHALL persist the queued Task, including optional purpose and submission-time History context, and ensure that the on-demand Task Runtime is active or awakened before returning. Success SHALL contain exactly:

```json
{"task":"geometry-build-cache-000"}
```

The submitting CLI process SHALL NOT wait for the Python file to finish. A later Python failure or Task Runtime failure SHALL be observed through the Task command surface rather than retroactively changing the already successful submission response.

#### Scenario: Async Task is accepted
- **WHEN** Task creation and runtime handoff succeed
- **THEN** `exec --async` exits with status `0`
- **AND** emits only the Task id
- **AND** the Task is initially observable as `queued` until its bound Houdini execution starts

#### Scenario: Runtime handoff cannot be established
- **WHEN** the Task cannot be committed into a state from which an active/recoverable Task Runtime can process it
- **THEN** the command fails through the common BridgeError envelope
- **AND** it does not report a successful Task submission that can be stranded permanently

### Requirement: Preserve the minimal successful synchronous execution envelope

A successful synchronous execution SHALL NOT add generic `ok`, `status`, or persistent execution-identity fields. Result/stdout/stderr bodies SHALL first be considered independently against the common `[output].inline_max_tokens` threshold. A non-empty body that fits SHALL remain inline without a per-artifact Resource field. A body that exceeds the threshold SHALL be materialized as a Resource and omitted inline. After that envelope is constructed, the complete envelope SHALL still pass through the common whole-result Output Policy and fixed serialized JSON hard limit.

The success object MAY contain only fields required by produced output:

| Field | Type | Presence |
| --- | --- | --- |
| `resource` | string | Present when the declared `result` body is Resource-backed. |
| `mime` | string | Present with a Resource-backed declared result. |
| `result` | JSON value/string | Present only when the declared result fits the common inline threshold. |
| `tokens` | integer | Present when the declared result is Resource-backed and a token count is known. |
| `stdout_resource` | string | Present only when stdout exceeds the common inline threshold and is Resource-backed. |
| `stdout` | string | Present only when non-empty stdout fits the common inline threshold. |
| `stderr_resource` | string | Present only when stderr exceeds the common inline threshold and is Resource-backed. |
| `stderr` | string | Present only when non-empty stderr fits the common inline threshold. |

A synchronous execution that produces no public output MAY emit `{}`.

#### Scenario: Small JSON result
- **WHEN** a successful synchronous result is JSON and fits the effective inline token threshold
- **THEN** output includes the decoded `result`
- **AND** no per-result `resource` field is required

#### Scenario: Large text result
- **WHEN** a synchronous result body exceeds the effective inline token threshold
- **THEN** output includes its `resource` and `mime`
- **AND** omits `result`
- **AND** includes `tokens` when known

#### Scenario: Small stdout
- **WHEN** synchronous stdout exists and fits the effective inline token threshold
- **THEN** output contains `stdout`
- **AND** omits `stdout_resource`

#### Scenario: Large stdout
- **WHEN** synchronous stdout exceeds the effective inline token threshold
- **THEN** output contains `stdout_resource`
- **AND** omits inline `stdout`

### Requirement: Emit the synchronous execution failure envelope

A Python failure during synchronous execution SHALL use:

```json
{
  "error": true,
  "code": "execution_failed",
  "message": "Python execution failed inside Houdini.",
  "resource": "<error-resource-id>"
}
```

`resource` is optional when no traceback Resource is available. `stdout_resource`, `stdout`, `stderr_resource`, and `stderr` MAY additionally appear when those outputs exist.

#### Scenario: Python raises during synchronous execution
- **WHEN** user Python fails before a synchronous `exec` returns
- **THEN** the output includes `error: true`, `code: "execution_failed"`, and the public message
- **AND** the command exits with status `1`

### Requirement: Use shared BridgeError handling for pre-dispatch failures

File-read errors, invalid option values, target-probe failures, and connection failures that occur before synchronous dispatch or asynchronous Task acceptance SHALL use the common BridgeError JSON envelope.

#### Scenario: Python file cannot be read
- **WHEN** `--file` names a file Houbridge cannot read using Python source-encoding rules
- **THEN** the command exits with status `1`
- **AND** emits the common BridgeError envelope with a file-read error code
