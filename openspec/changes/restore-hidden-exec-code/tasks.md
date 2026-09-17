# Tasks

## 1. Specification

- [x] 1.1 Define the hidden wrapper-only `--code --no-history` contract.
- [x] 1.2 Define synchronous-only, script-argument, and no-file-provenance semantics.
- [x] 1.3 Define invocation-local History suppression without changing History persistence schema.

## 2. Implementation

- [x] 2.1 Add hidden Typer options and validate the wrapper-only option combinations before dispatch.
- [x] 2.2 Add direct-source invocation construction with no source path and wrapper-provided script argv.
- [x] 2.3 Omit `__file__` for direct source while preserving file-backed runtime behavior.
- [x] 2.4 Suppress synchronous History composition for the hidden direct-source path.

## 3. Verification

- [x] 3.1 Verify hidden options do not appear in `exec --help`.
- [x] 3.2 Verify direct source reaches synchronous Execution with History disabled.
- [x] 3.3 Verify invalid `--code`/`--no-history`/`--async` combinations are rejected before dispatch and direct-source script arguments are preserved.
- [x] 3.4 Verify direct-source namespace omits synthetic file provenance and exposes the `<houbridge-code>` argv sentinel plus caller arguments.
- [ ] 3.5 Run the relevant unit suite in an environment with the project test dependencies available.
