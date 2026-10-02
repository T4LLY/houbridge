# Tasks

## 1. Specification

- [x] 1.1 Define synchronous caller-file import-root resolution against frozen invocation cwd.
- [x] 1.2 Define temporary `sys.path` prepend and exact restoration behavior.
- [x] 1.3 Keep direct-source and Async Task semantics outside this change.

## 2. Implementation

- [x] 2.1 Stage the resolved caller-file parent directory for synchronous file-backed execution.
- [x] 2.2 Prepend the staged import root before caller Python executes.
- [x] 2.3 Restore the prior Houdini `sys.path` on both success and Python failure.

## 3. Verification

- [x] 3.1 Verify a synchronous caller file can import a sibling helper from its own directory.
- [x] 3.2 Verify a relative caller path resolves its import root against invocation origin cwd rather than Houdini cwd.
- [x] 3.3 Verify `sys.path` is restored after caller Python raises.
- [x] 3.4 Run the relevant unit suite in an environment with the project test dependencies available.
