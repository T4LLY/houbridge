# Tasks

## 1. Specification

- [x] 1.1 Trace the current synchronous Exec path from CLI parsing through `ExecutionRuntime`, `ExecutionResultPresenter`, common Output Policy, Resource fallback, and final serialized JSON hard limit.
- [x] 1.2 Record the existing target-selection contract and preserve `--session`; do not reintroduce removed public `--port` or `--hcommand` options.
- [x] 1.3 Define `exec --full` as a synchronous-only transport exception in command-exec, Execution, Output Policy, and common command-contract deltas.
- [x] 1.4 Preserve `resource get --full` and all Resource/Task behavior unchanged.

## 2. Implementation

- [ ] 2.1 Add the `--full` Exec option and reject `--full --async` as a CLI usage error before dispatch or Task creation.
- [ ] 2.2 Select full-vs-normal presentation at the CLI/presenter boundary without propagating the mode into `ExecutionRuntime` or Houdini-injected execution code.
- [ ] 2.3 In full presentation mode, keep non-empty declared result/stdout/stderr inline and preserve existing type and presence rules without size-control Resources.
- [ ] 2.4 Keep traceback Resource behavior and the existing synchronous Python-failure envelope unchanged.
- [ ] 2.5 Emit the full Execution envelope with the canonical JSON serializer while bypassing whole-result Resource fallback and the fixed final serialized JSON size guard only for `exec --full`.
- [ ] 2.6 Leave normal Exec, Resource, Task, Search, Capture, History, and common Output behavior unchanged.

## 3. Tests

- [ ] 3.1 Verify normal Exec small stdout remains inline.
- [ ] 3.2 Verify normal Exec oversized stdout remains Resource-backed.
- [ ] 3.3 Verify `exec --full` returns oversized stdout completely inline without a Resource substitution.
- [ ] 3.4 Verify `exec --full` returns oversized declared result completely inline with its existing result type semantics.
- [ ] 3.5 Verify `exec --full` returns oversized stderr completely inline and separate from stdout.
- [ ] 3.6 Use a fixture larger than 65536 serialized bytes and verify `exec --full` neither Resource-fallbacks nor raises `output_too_large`.
- [ ] 3.7 Verify `--full --async` exits as a CLI usage error and does not submit a Task.
- [ ] 3.8 Verify full mode preserves the existing stdout/stderr/result presence and omission rules, including a synchronous Python failure with captured streams.
- [ ] 3.9 Run the existing non-full Exec, Execution presentation, Output Policy, Resource, and Task regression tests and confirm their contracts remain unchanged.

## 4. Conformance

- [ ] 4.1 Re-read the modified OpenSpec capabilities against the implementation and tests.
- [ ] 4.2 Confirm `resource get --full` remains bounded by the existing final CLI hard boundary.
- [ ] 4.3 Confirm no unrelated public option, output mode, persistence rule, or Resource/Task behavior changed.
