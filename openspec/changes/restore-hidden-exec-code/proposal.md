# Restore Hidden Exec Code Wrapper Path

## Why

External command wrappers need a low-overhead synchronous path for submitting short Python source directly to Houbridge without first creating a caller-side file. This path is not intended for normal users or AI/tool command discovery, and direct source has no truthful file provenance for Action History.

## What Changes

- Restore `exec --code TEXT` as a hidden wrapper-only option.
- Add hidden `--no-history` and require it whenever `--code` is used.
- Keep the documented/public Exec surface file-backed; neither hidden option appears in `exec --help`.
- Restrict direct source to synchronous execution, reject `--async`, preserve trailing script arguments after `--`, and reject combining `--code` with `--file`.
- Execute direct source with `__name__ == "__main__"` without inventing `__file__`; expose caller script arguments through `sys.argv` using the non-file `<houbridge-code>` sentinel at index 0.
- Treat `--no-history` as an invocation-local History override that skips History setup, embedding, Action Change capture, and final entry creation.

## Specification Impact

This change modifies the `command-exec`, `execution`, and `history` capabilities. Task remains file-backed and unchanged because direct source cannot be submitted asynchronously.

## Scope

In scope:

- hidden wrapper-only direct-source CLI parsing,
- synchronous Execution invocation construction,
- direct-source namespace semantics,
- invocation-local History suppression,
- CLI and Execution regression tests.

Out of scope:

- exposing direct source in public help, completion documentation, or AI Skills,
- asynchronous direct-source Tasks,
- History schema changes or synthetic file identities,
- changes to normal `exec --file` behavior.
