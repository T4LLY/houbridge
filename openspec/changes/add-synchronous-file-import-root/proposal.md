# Add Synchronous File Import Root

## Why

`houbridge exec --file` already exposes caller-file `__file__` and `sys.argv`, but synchronous execution currently compiles the already-read source inside Houdini without making the caller file's directory importable. A normal Python script can import sibling modules from its own directory, so fixed multi-file script bundles cannot currently be promoted into wrapper CLIs without adding wrapper-specific path manipulation or rewriting the scripts.

## What Changes

- Resolve the synchronous caller file's parent directory from the caller-supplied file path and the frozen invocation origin cwd.
- Temporarily prepend that directory to Houdini `sys.path` while caller Python executes.
- Restore the previous Houdini `sys.path` exactly after caller execution, including Python-exception paths.
- Leave direct source and asynchronous Task execution unchanged.

## Specification Impact

This change modifies the `execution` capability only. It does not change command syntax, public output schemas, Task persistence, or History behavior.

## Scope

In scope:

- synchronous file-backed Execution import-root semantics,
- relative caller path resolution against invocation origin cwd,
- exact `sys.path` cleanup,
- sibling-import regression coverage.

Out of scope:

- Python package execution through `-m` semantics,
- synthetic `__package__` values or entrypoint-relative imports using leading dots,
- arbitrary wrapper-side runners,
- asynchronous Task import-root changes.
