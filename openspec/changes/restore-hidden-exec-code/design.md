# Design: Hidden Exec Code Wrapper Path

## Decision

Keep the public Exec contract file-backed and add narrow hidden parser controls for trusted wrappers. `--code` and `--no-history` are Click/Typer hidden options. Direct source is accepted only when `--no-history` is also present and execution is synchronous. Synchronous file-backed execution may independently use hidden `--no-history`. Any `--no-history --async` combination is rejected before Task submission.

## Source representation

`ExecutionInvocation.source_path` is optional. File-backed invocation keeps the existing caller path and argv. Direct-source invocation uses `source_path = None` and builds argv as `("<houbridge-code>", *caller_args)`. The Houdini execution runtime sets `__file__` and uses the caller path as the compile filename only for file-backed invocation; direct source omits `__file__` and uses an internal diagnostic compile label.

This avoids fabricating file provenance solely to satisfy an implementation assumption.

## History boundary

The CLI composition root decides whether to construct `SynchronousExecutionHistory`. Normal synchronous file execution follows `[history].enabled` unless hidden `--no-history` is supplied. Hidden direct-source execution requires `--no-history`. In either case the override prevents construction of the History adapter even when configuration enables History.

The override stays outside `ExecutionInvocation`: History policy belongs to composition, not to the source model or runtime. Async execution does not accept the override, so Task submission keeps its existing configuration-derived History policy.

## Discovery boundary

The hidden options are intentionally omitted from generated command help. The source comment records that these controls exist for trusted wrappers and must not be advertised to AI/tool callers. This is a discovery/usage boundary, not a security boundary against a process that can inspect Houbridge source code.
