# Exec Command Specification

## Purpose

Define the public syntax, options, and JSON response contract for executing a caller-side Python file inside the selected local Houdini session, either synchronously or as an asynchronous Task.

## Requirements

### Requirement: Execute exactly one caller-side Python file

The command syntax SHALL be:

```text
houbridge exec --file PATH [--purpose TEXT] [--async] [--port INTEGER] [--root PATH] [--hcommand TEXT] [-- SCRIPT_ARGS...]
```

`--file` is required. The file SHALL be read as UTF-8 by Houbridge before dispatch. Arguments after `--` SHALL become the executed file's arguments.

| Option | Constraint | Default / behavior |
| --- | --- | --- |
| `--file PATH` | required readable file path | Python source read on the Houbridge side. |
| `--purpose TEXT` | optional text | Human/AI-supplied purpose recorded with enabled session Action History. |
| `--async` | boolean flag | Submit the file as an asynchronous Task instead of waiting for Python completion. |
| `--port INTEGER` | `1..65535` | Common local target option. |
| `--root PATH` | optional | Common runtime option. |
| `--hcommand TEXT` | optional | Common runtime option. |

#### Scenario: Execute a file synchronously
- **WHEN** `houbridge exec --file tool.py` is invoked without `--async`
- **THEN** Houbridge reads `tool.py` as UTF-8
- **AND** waits for that Python execution to complete before returning its execution result

#### Scenario: Execute a file with script arguments
- **WHEN** `houbridge exec --file tool.py -- one two` is invoked
- **THEN** Houdini receives `sys.argv` equivalent to `[<supplied-file-path>, "one", "two"]`

#### Scenario: Submit a file asynchronously
- **WHEN** `houbridge exec --file tool.py --async -- --quality high` is invoked
- **THEN** the exact source read for submission is used to create the Task
- **AND** `--quality` and `high` are stored as Task arguments

#### Scenario: Supply execution purpose
- **WHEN** `houbridge exec --file tool.py --purpose "build preview geometry"` is invoked
- **THEN** the purpose is available to enabled Action History for that execution
- **AND** it is not injected into the caller script's `sys.argv`

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

A successful synchronous execution SHALL NOT add generic `ok`, `status`, or persistent execution-identity fields. The success object MAY contain only fields required by produced output:

| Field | Type | Presence |
| --- | --- | --- |
| `resource` | string | Present when the execution produced a result Resource. |
| `mime` | string | Present when the result Resource has a MIME type. |
| `result` | JSON value/string | Present only when the common inline policy permits the result body. |
| `tokens` | integer | Present when the result is not inline and a token count is known. |
| `stdout_resource` | string | Present when stdout is Resource-backed. |
| `stdout` | string | Present when stdout exists and the common inline policy permits it. |
| `stderr_resource` | string | Present when stderr is Resource-backed. |
| `stderr` | string | Present when stderr exists and the common inline policy permits it. |

A synchronous execution that produces no public output MAY emit `{}`.

#### Scenario: Small JSON result
- **WHEN** a successful synchronous result is JSON and fits the effective inline token threshold
- **THEN** output includes the decoded `result`
- **AND** includes the result Resource fields when the result is materialized as a Resource

#### Scenario: Large text result
- **WHEN** a synchronous result body exceeds the effective inline token threshold
- **THEN** output includes its `resource`
- **AND** omits `result`
- **AND** includes `tokens` when known

#### Scenario: Small stdout
- **WHEN** synchronous stdout exists and fits inline
- **THEN** output may contain `stdout` together with `stdout_resource` when stdout is Resource-backed

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
- **WHEN** `--file` names a file Houbridge cannot read as UTF-8
- **THEN** the command exits with status `1`
- **AND** emits the common BridgeError envelope with a file-read error code
