# Execution Feature Specification

## Purpose

Define caller-provided Houdini Python execution, caller-file execution, execution output capture, target serialization, and invocation-local lifecycle. Command JSON schemas are specified separately.

## Requirements

### Requirement: Execute arbitrary Houdini Python

Execution SHALL accept caller-provided Python source and execute it inside the selected running Houdini session using Houdini's native Python environment. Multiline source, quotes, Unicode, and other valid Python source SHALL be transported without shell re-quoting changing the source contents.

#### Scenario: Execute multiline Unicode source
- **WHEN** source contains multiple lines, quotes, or Unicode text
- **THEN** the source compiled inside Houdini is semantically identical to the source supplied to Houbridge

### Requirement: Preserve the execution namespace contract

User code SHALL execute with `__name__ == "__main__"`. File execution SHALL additionally expose the caller-supplied file path as `__file__`. Inline execution SHALL not invent file-only context.

#### Scenario: Execute a caller-side Python file
- **WHEN** Execution is given a file source path
- **THEN** Houbridge reads the source on the host side
- **AND** Houdini executes that source with `__name__` set to `__main__`
- **AND** `__file__` is set to the supplied file path

#### Scenario: Execute inline source
- **WHEN** source is supplied directly rather than from a file
- **THEN** Execution uses the normal `__main__` namespace
- **AND** does not invent file arguments or file provenance

### Requirement: Support caller-file arguments without consuming them as Houbridge options

File execution SHALL support script arguments that become the executed file's `sys.argv`. `sys.argv[0]` SHALL be the supplied file path and following values SHALL be the caller's file arguments. Houdini's previous `sys.argv` SHALL be restored whether user code succeeds or raises.

#### Scenario: File receives arguments
- **WHEN** a file execution includes caller script arguments
- **THEN** user code observes the specified argv values

#### Scenario: User code raises
- **WHEN** execution temporarily changes `sys.argv` for the file and the user source raises
- **THEN** Houdini's prior `sys.argv` is restored in the execution cleanup path

### Requirement: Keep inline and file source modes exclusive

One user execution SHALL have exactly one source mode. File-only arguments SHALL not be accepted for inline source.

#### Scenario: Both source modes are selected
- **WHEN** both inline source and a file source are supplied
- **THEN** Execution rejects the request before dispatch

#### Scenario: No source is selected
- **WHEN** neither source mode is supplied
- **THEN** Execution rejects the request before dispatch

#### Scenario: Inline source receives file arguments
- **WHEN** file arguments are supplied without file mode
- **THEN** Execution rejects the request before dispatch

### Requirement: Capture stdout, stderr, result, and Python failure diagnostics

Execution SHALL capture stdout, stderr, a declared `result` value, and Python exception traceback without streaming unbounded bodies directly from Houdini to the caller.

#### Scenario: User Python writes stdout and stderr
- **WHEN** user source completes
- **THEN** both streams are captured independently

#### Scenario: User Python raises
- **WHEN** an exception escapes caller source
- **THEN** the traceback is captured as the execution failure diagnostic
- **AND** stdout/stderr already produced by the source remain available

### Requirement: Classify execution results deterministically

When the execution namespace contains `result`, Execution SHALL classify the value as follows:

- a string that parses as JSON is JSON content without double encoding,
- a string that does not parse as JSON is plain text,
- a non-string JSON-serializable value is serialized as JSON,
- a non-JSON-serializable value is represented with a bounded `reprlib` representation as plain text.

#### Scenario: Result is a JSON string
- **WHEN** `result` is a string containing valid JSON
- **THEN** it is classified as JSON rather than JSON-encoded a second time

#### Scenario: Result is an arbitrary Python object
- **WHEN** JSON serialization fails for `result`
- **THEN** Execution returns a bounded textual representation rather than failing solely because the result object is not JSON-serializable

### Requirement: Route execution output through Resource and Output boundaries

Execution SHALL return its logical result/stdout/stderr/failure data through the shared Resource and Output boundaries defined by their specifications. Execution SHALL not implement a separate token-limit or hard-output policy.

#### Scenario: Result fits inline policy
- **WHEN** a result is small enough for the common inline policy
- **THEN** the command contract may expose the inline value together with any required Resource reference

#### Scenario: Result exceeds inline policy
- **WHEN** a result is too large for direct CLI output
- **THEN** the complete payload remains inspectable through the Resource subsystem
- **AND** the common Output policy determines the final bounded response

### Requirement: Keep execution persistence invocation-local

Execution SHALL not require a project database or persistent execution record. Source text, filename, argv, status, timing, and other execution-specific metadata SHALL be used for the current invocation only unless they are part of a generic Resource payload explicitly produced by that invocation.

#### Scenario: Execution completes
- **WHEN** result collection and final output construction finish
- **THEN** no execution record is required for later commands

#### Scenario: File execution completes
- **WHEN** `exec --file` succeeds
- **THEN** the file can be executed without updating a persistent use counter or execution log

### Requirement: Serialize execution per Houdini target

Concurrent managed executions directed at the same Houdini target SHALL be serialized by a target-scoped lock. Different independent targets MAY proceed independently. The lock SHALL cover dispatch and output collection required to keep one invocation coherent.

#### Scenario: Two executions overlap on one target
- **WHEN** two callers attempt execution against the same target
- **THEN** only one owns the target execution lock at a time
- **AND** the later caller does not interleave its managed execution with the earlier one

### Requirement: Use invocation-local execution files

Execution MAY use a unique temporary directory and generated runnable script for transport and result exchange. Such files SHALL be operational invocation state rather than project persistence. Reusable Houdini-side implementation SHALL live below `houbridge/houdini/scripts/execution/`.

#### Scenario: Start a new execution
- **WHEN** dispatch begins
- **THEN** the invocation receives isolated temporary transport/result paths
- **AND** reusable execution logic comes from the Execution injected-script boundary

#### Scenario: Normal execution finishes
- **WHEN** Houdini and host-side result collection are complete
- **THEN** temporary invocation files are eligible for cleanup

### Requirement: Use the selected existing Houdini openport session

Normal Execution SHALL target the selected reachable local Houdini openport through SideFX `hcommand`.

#### Scenario: Selected target is reachable
- **WHEN** the configured local openport responds
- **THEN** Execution dispatches the invocation-local Houdini script to that session

#### Scenario: Selected target is unreachable
- **WHEN** SideFX transport cannot reach the selected local openport
- **THEN** Execution reports a connection or transport failure

### Requirement: Surface SideFX transport failures without fabricating Python success

Non-zero `hcommand` exits and transport failures SHALL be reported as execution/transport failures. A transport failure SHALL not be converted into a successful Python result.

#### Scenario: hcommand exits non-zero
- **WHEN** SideFX transport reports a non-zero exit
- **THEN** Execution reports the transport failure
- **AND** does not fabricate a successful result
