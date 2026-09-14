# Design

## 1. Goal

Add one explicit machine-to-machine transport mode for synchronous Exec without changing the low-level Execution contract or weakening the common Output/Resource boundaries for any other command.

## 2. Current Boundary

The current implementation already separates the relevant responsibilities:

- `ExecutionRuntime` returns an `ExecutionOutcome` containing the captured declared result, stdout, stderr, traceback, and Python success state.
- `ExecutionResultPresenter` converts that outcome into the synchronous Exec command envelope and applies per-artifact inline-vs-Resource decisions.
- The Exec CLI passes that completed envelope to the common Output path, which may Resource-fallback the whole logical result and then enforces the fixed final serialized JSON hard limit.

The full-output feature SHALL preserve this separation rather than adding an alternate execution engine.

## 3. Full-Mode Selection

`--full` is a CLI presentation/transport choice, not an Execution-runtime semantic. The flag SHALL NOT be propagated into Houdini-injected code, `ExecutionRuntime`, Session resolution, History, Resource persistence, or Task runtime state.

The CLI SHALL select the synchronous presentation mode close to the existing `ExecutionResultPresenter` construction boundary. Normal mode uses the existing size-aware presenter behavior. Full mode uses the same logical presenter contract but forces declared result/stdout/stderr bodies to remain inline.

## 4. Per-Artifact Presentation

Normal synchronous Exec keeps the current behavior exactly.

Full synchronous Exec SHALL:

- decode/classify the declared result exactly as normal synchronous Exec does,
- include the declared result as `result` when non-empty,
- include non-empty stdout as `stdout`,
- include non-empty stderr as `stderr`,
- omit the normal size-control `resource`, `stdout_resource`, and `stderr_resource` substitutions for those bodies,
- preserve the existing omission rules for absent/empty bodies.

The existing synchronous Python-failure envelope remains authoritative. A traceback may continue to be stored in the existing `resource` field because that Resource is part of the failure contract rather than a size-control replacement for `result`. In full mode, captured stdout/stderr accompanying that failure still remain inline regardless of size.

No `result_resource` field is introduced; the current successful declared-result Resource field is named `resource` and remains unchanged in normal mode.

## 5. Final CLI Emission

Normal synchronous Exec SHALL continue through the existing common Output Policy and fixed 65536-byte final JSON guard.

Full synchronous Exec SHALL serialize its already-built command envelope with the existing canonical public JSON serializer and write exactly one JSON object plus newline directly to stdout. It SHALL NOT invoke whole-result Resource fallback or the fixed final size guard for that successful or Python-failure Execution envelope.

The exception SHALL remain scoped to the `exec --full` command path. The common Output Policy's normal limits and Resource subsystem semantics SHALL NOT be globally weakened or parameterized into an unrestricted bypass available to unrelated commands.

Pre-dispatch and transport `BridgeError` handling remains on the existing common bounded error path. `exec --full` does not define a second error envelope.

## 6. Async Rejection

`--full` and `--async` are mutually exclusive. Their combination SHALL fail as a CLI usage error before file execution is dispatched and before a Task is created.

## 7. Existing Target Selection

The current OpenSpec target-selection contract remains authoritative: Exec selects an existing registered Houdini session with `--session`. Public `--port` and `--hcommand` options are not reintroduced by this change.

## 8. Verification

Tests SHALL prove both sides of the branch:

- normal Exec still Resource-backs oversized per-artifact output and still obeys the common hard boundary,
- full Exec returns complete >64 KiB result/stdout/stderr inline without Resource fallback or truncation,
- full Exec preserves normal result types, output field presence/omission rules, stdout/stderr separation, and Python-failure semantics,
- full+async is rejected before Task submission,
- existing non-full Exec tests continue to pass unchanged.
