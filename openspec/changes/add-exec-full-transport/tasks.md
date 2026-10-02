# Tasks

## 1. Specification

- [x] 1.1 Trace the current synchronous Exec path from CLI parsing through `ExecutionRuntime`, `ExecutionResultPresenter`, common Output Policy, Resource fallback, and final serialized JSON hard limit.
- [x] 1.2 Record the existing target-selection contract and preserve `--session`; do not reintroduce removed public `--port` or `--hcommand` options.
- [x] 1.3 Define `exec --full` as a synchronous-only transport exception in command-exec, Execution, Output Policy, and common command-contract deltas.
- [x] 1.4 Preserve `resource get --full` and all Resource/Task behavior unchanged.
- [x] 1.5 Define `result_kind` metadata for declared results returned by `exec --full`.

## 2. Implementation

- [x] 2.1 Add the `--full` Exec option and reject `--full --async` as a CLI usage error before dispatch or Task creation.
- [x] 2.2 Select full-vs-normal presentation at the CLI/presenter boundary without propagating the mode into `ExecutionRuntime` or Houdini-injected execution code.
- [x] 2.3 In full presentation mode, keep non-empty declared result/stdout/stderr inline and preserve existing type and presence rules without size-control Resources.
- [x] 2.4 Keep traceback Resource behavior and the existing synchronous Python-failure envelope unchanged.
- [x] 2.5 Emit the full Execution envelope with the canonical JSON serializer while bypassing whole-result Resource fallback and the fixed final serialized JSON size guard only for `exec --full`.
- [x] 2.6 Add `result_kind` only to full-mode envelopes that contain a declared result; leave normal Exec envelopes unchanged.
- [x] 2.7 Leave Resource, Task, Search, Capture, History, and common Output behavior unchanged.

## 3. Tests

- [x] 3.1 Verify normal Exec small stdout remains inline.
- [x] 3.2 Verify normal Exec oversized stdout remains Resource-backed.
- [x] 3.3 Verify `exec --full` returns oversized stdout completely inline without a Resource substitution.
- [x] 3.4 Verify `exec --full` returns oversized declared result completely inline with its existing result type semantics.
- [x] 3.5 Verify `exec --full` returns oversized stderr completely inline and separate from stdout.
- [x] 3.6 Use a fixture larger than 65536 serialized bytes and verify `exec --full` neither Resource-fallbacks nor raises `output_too_large`.
- [x] 3.7 Verify `--full --async` exits as a CLI usage error and does not submit a Task.
- [x] 3.8 Verify full mode preserves the existing stdout/stderr/result presence and omission rules, including a synchronous Python failure with captured streams.
- [x] 3.9 Verify full mode reports `result_kind=json` and `result_kind=text` without inferring from the decoded result value.
- [x] 3.10 Run the existing non-full Exec, Execution presentation, Output Policy, Resource, and Task regression tests and confirm their contracts remain unchanged.

## 4. Conformance

- [x] 4.1 Re-read the modified OpenSpec capabilities against the implementation and tests.
- [x] 4.2 Confirm `resource get --full` remains bounded by the existing final CLI hard boundary.
- [x] 4.3 Confirm no unrelated public option, output mode, persistence rule, or Resource/Task behavior changed.
