## MODIFIED Requirements

### Requirement: Capture stdout, stderr, result, and Python failure diagnostics

The low-level execution boundary SHALL be able to capture stdout, stderr, a declared `result` value, and Python exception traceback without coupling capture semantics to public CLI size policy. Synchronous Exec MAY expose all of these according to its command contract. Normal synchronous Exec SHALL use the bounded Resource/Output presentation path, while explicit `exec --full` MAY return the complete synchronous result/stdout/stderr bodies directly in its single JSON Execution envelope. Async Task SHALL persist its defined stdout/stderr Task streams and terminal state according to the Task specification.

#### Scenario: User Python writes stdout and stderr
- **WHEN** user source produces both streams
- **THEN** they are captured independently

#### Scenario: User Python raises
- **WHEN** an exception escapes caller source
- **THEN** the traceback is captured as the Python failure diagnostic
- **AND** stdout/stderr already produced by the source remain available to the owning synchronous or Task execution path

#### Scenario: Full output is selected
- **WHEN** the owning command is synchronous `exec --full`
- **THEN** the captured result/stdout/stderr values are unchanged from the values produced by the same Execution without `--full`
- **AND** the full presentation may additionally expose the already-known declared-result classification as transport metadata
- **AND** only size-control presentation and that classification metadata differ

### Requirement: Route synchronous execution output through Resource and Output boundaries

Normal synchronous Execution without `--full` SHALL hand each non-empty declared result/stdout/stderr body to the common Output decision boundary using the shared token estimator. Bodies at or below the effective inline threshold SHALL remain inline and SHALL not be duplicated into per-artifact Resources solely for size control. Bodies above the threshold SHALL be materialized through Resource and replaced in the command envelope by their defined Resource reference fields. The completed normal command envelope SHALL then pass through the common whole-result Output Policy and serialized hard-output guard. Execution SHALL not implement a separate token estimator, threshold, or hard-output policy.

Synchronous `exec --full` SHALL be the sole Execution presentation exception: after the same underlying `ExecutionOutcome` is produced, result/stdout/stderr SHALL bypass the per-artifact size decision and remain inline, and the completed Execution envelope SHALL bypass whole-result Resource fallback and the fixed serialized hard-output guard. This exception SHALL be selected at the CLI/presentation boundary and SHALL NOT alter `ExecutionRuntime`, injected caller execution, result classification, stdout/stderr capture, Session resolution, History, or Task semantics.

#### Scenario: Result fits inline policy
- **WHEN** a normal synchronous result is small enough for the common inline policy
- **THEN** the command contract exposes the inline value
- **AND** no per-result Resource is created solely for size control

#### Scenario: Result exceeds inline policy
- **WHEN** a normal synchronous result is too large for direct CLI output
- **THEN** that result body is materialized through Resource and omitted inline
- **AND** the completed envelope still passes through the common Output policy

#### Scenario: Full result exceeds normal inline and hard limits
- **WHEN** `exec --full` produces result/stdout/stderr whose completed JSON envelope exceeds the normal soft or hard output limits
- **THEN** the same underlying Execution values remain inline in the completed envelope
- **AND** no size-control Resource fallback is applied to those values or to the whole envelope
