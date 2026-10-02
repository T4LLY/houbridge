# Add Exec Full Transport Mode

## Why

Houbridge synchronous Exec currently applies per-artifact inline limits, Resource fallback, whole-result Output Policy, and the fixed serialized JSON hard boundary. That behavior is appropriate for human-facing CLI use, but it prevents another local CLI from using Houbridge as a direct machine-to-machine transport for a complete synchronous Execution result without an additional Resource retrieval round trip.

A narrowly scoped `exec --full` mode is needed so local wrapper CLIs can receive the complete synchronous `result`, `stdout`, and `stderr` in one compact JSON response while preserving the existing Execution semantics and leaving every existing non-full command path unchanged. Full transport also needs to expose the already-known declared-result classification so a wrapper can distinguish plain text from a JSON string without guessing from the decoded value.

## What Changes

- Add `--full` to synchronous `houbridge exec`.
- Reject `--full --async` as a CLI usage error before Task submission.
- Keep normal synchronous Exec behavior unchanged, including per-artifact Resource fallback, whole-result Output Policy, and the fixed 65536-byte serialized JSON hard boundary.
- In `exec --full` only, keep non-empty declared result/stdout/stderr bodies inline regardless of `[output].inline_max_tokens`, do not create size-control Resources for those bodies, skip whole-result Resource fallback, and skip the fixed final serialized JSON size guard.
- Preserve the existing result classification and expose it as `result_kind: "json" | "text"` whenever full mode returns a declared `result`.
- Preserve stdout/stderr separation, remaining presence rules, Python failure envelope, traceback Resource behavior, and BridgeError handling.
- Keep `resource get --full`, Task output, Resource limits, global Output limits, and all other commands unchanged.

## Specification Impact

This change modifies the existing `command-exec`, `execution`, `output-policy`, and `command-contract` capabilities. `resource` and `command-resource` are intentionally unchanged because `resource get --full` retains its existing bounded semantics.

## Scope

In scope:

- OpenSpec contract for `exec --full`.
- A synchronous Exec-only Output Policy exception.
- CLI usage rejection for `--full --async`.
- Regression coverage for normal Exec and >64 KiB full-mode output.

Out of scope:

- `houlayout` changes.
- Public `--port` or `--hcommand` target selection.
- Resource subsystem redesign or removal.
- Normal Exec output-policy changes.
- Async Task output changes.
- `task get --full` or other new full-output commands.
- Arbitrary Python entry points or unrelated refactoring.
