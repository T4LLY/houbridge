## MODIFIED Requirements

### Requirement: Execute exactly one caller-side Python file

The command syntax SHALL be:

```text
houbridge exec --file PATH [--purpose TEXT] [--full] [--async] [--session INTEGER] [-- SCRIPT_ARGS...]
```

`--file` is required. Houbridge SHALL read the file using Python source-encoding rules compatible with `tokenize.open()` before dispatch. After decoding, source containing an actual NUL character (`U+0000`) SHALL be rejected with BridgeError code `invalid_python_source` before synchronous dispatch or asynchronous Task creation. Arguments after `--` SHALL become the executed file's arguments. Async Task metadata SHALL store the normalized absolute file path even when the caller supplied a relative path. `--full` SHALL be valid only for synchronous execution and SHALL be mutually exclusive with `--async`.

| Option | Constraint | Default / behavior |
| --- | --- | --- |
| `--file PATH` | required readable file path | Python source read on the Houbridge side. |
| `--purpose TEXT` | optional text | Human/AI-supplied purpose recorded with enabled session Action History. |
| `--full` | boolean flag; synchronous only | Return the complete synchronous Execution envelope without size-control Resource substitution, whole-result Resource fallback, or the fixed final serialized JSON hard guard. |
| `--async` | boolean flag; mutually exclusive with `--full` | Submit the file as an asynchronous Task instead of waiting for Python completion. |
| `--session INTEGER` | positive registered session number | Select this session instead of the registry primary. |

#### Scenario: Execute a file synchronously
- **WHEN** `houbridge exec --file tool.py` is invoked without `--async`
- **THEN** Houbridge reads `tool.py` using Python source-encoding rules
- **AND** waits for that Python execution to complete before returning its execution result

#### Scenario: Execute a file with script arguments
- **WHEN** `houbridge exec --file tool.py -- one two` is invoked
- **THEN** Houdini receives `sys.argv` equivalent to `[<supplied-file-path>, "one", "two"]`

#### Scenario: Execute synchronously with complete transport output
- **WHEN** `houbridge exec --full --file tool.py` is invoked
- **THEN** Houbridge waits for the Python execution to complete
- **AND** returns that synchronous Execution result under the full-output contract

#### Scenario: Submit a file asynchronously
- **WHEN** `houbridge exec --file tool.py --async -- --quality high` is invoked
- **THEN** the exact source read for submission is used to create the Task
- **AND** the Task stores the normalized absolute path of `tool.py`
- **AND** `--quality` and `high` are stored as Task arguments
- **AND** submission freezes the resolved dispatch context required for later Task Runtime execution, including the selected session number, resolved target port, PID/process incarnation, and required transport executable/environment/settings

#### Scenario: Full and async are combined
- **WHEN** `houbridge exec --full --async --file tool.py` is invoked
- **THEN** the command is rejected as a CLI usage error
- **AND** caller Python is not dispatched
- **AND** no asynchronous Task is created

#### Scenario: Supply execution purpose
- **WHEN** `houbridge exec --file tool.py --purpose "build preview geometry"` is invoked
- **THEN** the purpose is available to enabled Action History for that execution
- **AND** it is not injected into the caller script's `sys.argv`

#### Scenario: Source contains a NUL character
- **WHEN** the decoded Python file contains `U+0000`
- **THEN** Exec fails with `invalid_python_source` before caller Python is dispatched or an Async Task is created
- **AND** no Action History entry is created for that rejected source

### Requirement: Preserve the minimal successful synchronous execution envelope

A successful normal synchronous execution without `--full` SHALL NOT add generic `ok`, `status`, or persistent execution-identity fields. Result/stdout/stderr bodies SHALL first be considered independently against the common `[output].inline_max_tokens` threshold. A non-empty body that fits SHALL remain inline without a per-artifact Resource field. A body that exceeds the threshold SHALL be materialized as a Resource and omitted inline. After that envelope is constructed, the complete envelope SHALL still pass through the common whole-result Output Policy and fixed serialized JSON hard limit. `exec --full` is the sole synchronous Exec exception and SHALL follow the separate full-output requirement instead of these size-control rules.

The normal success object MAY contain only fields required by produced output:

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
- **WHEN** a successful normal synchronous result is JSON and fits the effective inline token threshold
- **THEN** output includes the decoded `result`
- **AND** no per-result `resource` field is required

#### Scenario: Large text result
- **WHEN** a normal synchronous result body exceeds the effective inline token threshold
- **THEN** output includes its `resource` and `mime`
- **AND** omits `result`
- **AND** includes `tokens` when known

#### Scenario: Small stdout
- **WHEN** normal synchronous stdout exists and fits the effective inline token threshold
- **THEN** output contains `stdout`
- **AND** omits `stdout_resource`

#### Scenario: Large stdout
- **WHEN** normal synchronous stdout exceeds the effective inline token threshold
- **THEN** output contains `stdout_resource`
- **AND** omits inline `stdout`

## ADDED Requirements

### Requirement: Return a complete synchronous Execution envelope with exec --full

`exec --full` SHALL be an explicit machine-to-machine transport mode for synchronous Execution. It SHALL preserve the existing Execution result classification, JSON value types, stdout/stderr separation, field names, and field presence/omission rules while bypassing only size-control presentation behavior.

For `exec --full`:

- a non-empty declared result SHALL be returned inline as `result` regardless of `[output].inline_max_tokens`,
- non-empty stdout SHALL be returned inline as `stdout` regardless of `[output].inline_max_tokens`,
- non-empty stderr SHALL be returned inline as `stderr` regardless of `[output].inline_max_tokens`,
- the declared result SHALL NOT be replaced by the normal size-control `resource`/`mime`/`tokens` fields,
- stdout and stderr SHALL NOT be replaced by `stdout_resource` or `stderr_resource` for size reasons,
- the completed Execution envelope SHALL NOT use whole-result Resource fallback,
- the completed Execution envelope SHALL NOT be rejected or replaced because it exceeds the fixed 65536-byte final serialized JSON hard boundary,
- the complete envelope SHALL still use the shared canonical public JSON serializer and SHALL be emitted as exactly one JSON object followed by a newline.

This full-output exception applies only to the synchronous Execution envelope. It does not redefine `resource get --full`, Resource inspection bounds, Async Task output, or any other command. It also does not remove the existing traceback `resource` from the synchronous Python-failure contract; that traceback Resource is not a size-control replacement for the declared result.

#### Scenario: Large stdout remains inline
- **WHEN** `exec --full` captures stdout larger than the configured inline threshold
- **THEN** the complete stdout is returned in `stdout`
- **AND** `stdout_resource` is omitted

#### Scenario: Large declared result remains inline
- **WHEN** `exec --full` captures a declared result larger than the configured inline threshold
- **THEN** the complete declared result is returned in `result` with its normal JSON-or-text type semantics
- **AND** no size-control `resource`, `mime`, or `tokens` replacement is emitted for that result

#### Scenario: Large stderr remains inline
- **WHEN** `exec --full` captures stderr larger than the configured inline threshold
- **THEN** the complete stderr is returned in `stderr`
- **AND** `stderr_resource` is omitted

#### Scenario: Full envelope exceeds the normal hard boundary
- **WHEN** the serialized `exec --full` Execution envelope exceeds 65536 bytes
- **THEN** Houbridge emits the complete envelope
- **AND** does not whole-result Resource-fallback it
- **AND** does not return `output_too_large` solely because of that size

#### Scenario: Full execution produces no public output
- **WHEN** `exec --full` has no declared result and stdout/stderr are empty
- **THEN** it preserves the existing omission rules and may emit `{}`

#### Scenario: Python fails in full mode
- **WHEN** caller Python fails during `exec --full` after producing stdout or stderr
- **THEN** the existing `execution_failed` envelope and exit status are preserved
- **AND** captured stdout/stderr remain completely inline regardless of size
- **AND** traceback Resource behavior remains unchanged
