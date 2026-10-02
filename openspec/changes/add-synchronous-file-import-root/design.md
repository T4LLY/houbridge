# Design: Synchronous File Import Root

## Decision

Keep the existing source transport unchanged and add one explicit synchronous execution-context field: the absolute parent directory of the caller file. The host computes this path before dispatch; the Houdini runtime temporarily prepends it to `sys.path` while the file source executes.

## Path resolution

`ExecutionInvocation.source_path` intentionally preserves the caller-supplied path because `__file__` and `sys.argv[0]` expose that value. Import-root resolution therefore MUST NOT normalize `source_path` in place.

For synchronous file execution:

1. if `source_path` is relative, resolve it against the invocation's frozen `origin_cwd`,
2. resolve the resulting path to an absolute filesystem path,
3. use its parent directory as the staged `source_import_root`.

This avoids depending on Houdini's current working directory, which may differ from the CLI caller's cwd.

## Houdini runtime

Immediately before caller execution, the runtime snapshots the current `sys.path`. For file-backed execution it prepends `source_import_root`, then restores the complete previous path in the same cleanup boundary that restores `sys.argv`.

Direct source has no caller file and therefore stages no import root.

The runtime does not manufacture package metadata or use `runpy.run_module`; ordinary sibling imports and imports from package directories below the caller-file directory are the supported script-style semantics.

## Async boundary

This change is intentionally synchronous-only because the wrapper-template transport is synchronous and Task has a separate persisted runtime contract. Async import semantics can be specified independently if a concrete need appears.
