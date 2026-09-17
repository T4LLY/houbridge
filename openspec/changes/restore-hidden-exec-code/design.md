# Design: Hidden Exec Code Wrapper Path

## Decision

Keep the public Exec contract file-backed and add a narrow hidden parser path for trusted wrappers. `--code` and `--no-history` are Click/Typer hidden options. A source string is accepted only when both hidden options are present and execution is synchronous.

## Source representation

`ExecutionInvocation.source_path` becomes optional. File-backed invocation keeps the existing caller path and argv. Direct-source invocation uses `source_path = None` and builds argv as `("<houbridge-code>", *caller_args)`. The Houdini execution runtime sets `__file__` and uses the caller path as the compile filename only for file-backed invocation; direct source omits `__file__` and uses an internal diagnostic compile label.

This avoids fabricating file provenance solely to satisfy an implementation assumption.

## History boundary

The CLI composition root decides whether to construct `SynchronousExecutionHistory`. Normal file execution continues to follow `[history].enabled`. Hidden direct-source execution requires `--no-history`, so the History adapter is not constructed even when configuration enables History.

The override stays outside `ExecutionInvocation`: History policy belongs to composition, not to the source model or runtime.

## Discovery boundary

The hidden options are intentionally omitted from generated command help. The source comment records that this path exists for trusted wrappers and must not be advertised to AI/tool callers. This is a discovery/usage boundary, not a security boundary against a process that can inspect Houbridge source code.
