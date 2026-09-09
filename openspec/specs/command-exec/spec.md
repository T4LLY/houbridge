# Exec Command Specification

## Purpose

Define the public syntax, options, and JSON response contract for executing Python inside the selected local Houdini session.

## Requirements

### Requirement: Expose exactly one execution-source mode

The command syntax SHALL be:

```text
houbridge exec (--code PYTHON | --file PATH) [OPTIONS] [-- SCRIPT_ARGS...]
```

Exactly one of `--code` or `--file` SHALL be supplied. Arguments after `--` SHALL be accepted only with `--file`.

| Option | Constraint | Default / behavior |
| --- | --- | --- |
| `--code TEXT` | mutually exclusive with `--file` | Python source executed in Houdini. |
| `--file PATH` | file path; mutually exclusive with `--code` | Read as UTF-8 on the Houbridge side. |
| `--inline-max-tokens INTEGER` | `0..4096` | Override the configured soft inline threshold for this invocation. |
| `--port INTEGER` | `1..65535` | Common local target option. |
| `--root PATH` | optional | Common runtime option. |
| `--hcommand TEXT` | optional | Common runtime option. |

#### Scenario: Execute inline Python
- **WHEN** `houbridge exec --code "result = 1"` is invoked
- **THEN** the provided source is the execution source
- **AND** no file argv is synthesized

#### Scenario: Execute a file with script arguments
- **WHEN** `houbridge exec --file tool.py -- one two` is invoked
- **THEN** `tool.py` is read as UTF-8 by Houbridge
- **AND** Houdini receives `sys.argv` equivalent to `[<file-name>, "one", "two"]`

#### Scenario: Both sources are supplied
- **WHEN** both `--code` and `--file` are supplied
- **THEN** the command fails with `execution_source_required`

#### Scenario: Script arguments are used with --code
- **WHEN** arguments after `--` accompany `--code`
- **THEN** the command fails with `file_arguments_require_file`

### Requirement: Preserve the minimal successful execution envelope

A successful execution SHALL NOT add generic `ok`, `status`, or persistent execution-identity fields. The success object MAY contain only fields required by produced output:

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

An execution that produces no public output MAY emit `{}`.

#### Scenario: Small JSON result
- **WHEN** a successful result is JSON and fits the effective inline token threshold
- **THEN** output includes the decoded `result`
- **AND** includes the result Resource fields when the result is materialized as a Resource

#### Scenario: Large text result
- **WHEN** a result body exceeds the effective inline token threshold
- **THEN** output includes its `resource`
- **AND** omits `result`
- **AND** includes `tokens` when known

#### Scenario: Small stdout
- **WHEN** stdout exists and fits inline
- **THEN** output may contain `stdout` together with `stdout_resource` when stdout is Resource-backed

### Requirement: Emit the execution failure envelope

A Python execution failure SHALL use:

```json
{
  "error": true,
  "code": "execution_failed",
  "message": "Python execution failed inside Houdini.",
  "resource": "<error-resource-id>"
}
```

`resource` is optional when no traceback Resource is available. `stdout_resource`, `stdout`, `stderr_resource`, and `stderr` MAY additionally appear when those outputs exist.

#### Scenario: Python raises inside Houdini
- **WHEN** user Python fails
- **THEN** the output includes `error: true`, `code: "execution_failed"`, and the public message
- **AND** the command exits with status `1`

### Requirement: Use shared BridgeError handling for pre-dispatch failures

File-read errors, invalid source selection, invalid option values, and connection failures that occur outside executed Python SHALL use the common BridgeError JSON envelope.

#### Scenario: Python file cannot be read
- **WHEN** `--file` names a file Houbridge cannot read as UTF-8
- **THEN** the command exits with status `1`
- **AND** emits the common BridgeError envelope with a file-read error code
