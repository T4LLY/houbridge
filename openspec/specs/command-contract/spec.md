# Command Contract Specification

## Purpose

Define the shared CLI syntax and JSON emission contract used by all Houbridge commands. Command-specific syntax, options, and success payloads are defined by the individual command specifications.

## Requirements

### Requirement: Keep the public command surface explicit

The Houbridge CLI SHALL expose the following command families in this specification set:

- `houbridge exec`
- `houbridge session ...`
- `houbridge capture ...`
- `houbridge search ...`
- `houbridge resource ...`
- `houbridge task ...`
- `houbridge history ...`

#### Scenario: Show top-level help
- **WHEN** the user requests top-level help
- **THEN** these command families are discoverable

### Requirement: Install one root console command

An installed Houbridge package SHALL expose a console command named `houbridge` as the root of the public CLI. The Python module/function used as the packaging entry point SHALL remain an implementation detail and SHALL NOT be frozen by this specification.

#### Scenario: Invoke the installed CLI
- **WHEN** Houbridge is installed through its supported Python packaging path
- **THEN** invoking `houbridge` reaches the public Houbridge CLI
- **AND** the package's internal entry-point module may be refactored without changing the public command name

### Requirement: Use compact JSON for dispatched command results

A successfully dispatched Houbridge command SHALL write exactly one compact JSON object followed by a newline for its machine result. JSON serialization SHALL use UTF-8, preserve non-ASCII text, and SHALL NOT add decorative Rich output or ANSI color to the JSON result.

#### Scenario: Command succeeds
- **WHEN** a command handler completes successfully
- **THEN** it emits one JSON object
- **AND** exits with status `0`
- **AND** the success object omits generic `ok` and `error` fields unless a command-specific schema explicitly requires otherwise

### Requirement: Use one common BridgeError envelope

A handled Houbridge failure SHALL emit:

```json
{"error":true,"code":"ERROR_CODE","message":"message"}
```

When non-empty diagnostic detail exists, `detail` SHALL be added:

```json
{"error":true,"code":"ERROR_CODE","message":"message","detail":"diagnostic detail"}
```

The failure envelope SHALL NOT add `ok`, a null `resource`, or other generic fields not defined above.

#### Scenario: BridgeError has no detail
- **WHEN** a command raises a handled `BridgeError` without detail
- **THEN** the JSON object contains exactly `error`, `code`, and `message`
- **AND** the process exits with status `1`

#### Scenario: BridgeError has detail
- **WHEN** a handled `BridgeError` contains non-empty detail
- **THEN** `detail` is included
- **AND** the process exits with status `1`

### Requirement: Wrap unexpected internal failures

An unexpected exception reaching the CLI process boundary SHALL be converted to:

```json
{
  "error": true,
  "code": "internal_error",
  "message": "Houbridge encountered an unexpected internal error.",
  "detail": "ExceptionType: message"
}
```

The common Output subsystem SHALL bound `detail` if required by the fixed output hard limit.

#### Scenario: Unexpected ValueError reaches main
- **WHEN** an unexpected `ValueError("boom")` escapes command handling
- **THEN** the command exits with status `1`
- **AND** the error code is `internal_error`
- **AND** detail identifies `ValueError: boom` unless the hard-output guard must omit it

### Requirement: Preserve framework usage errors as CLI text

Argument-parser failures that occur before a Houbridge command handler is dispatched SHALL remain framework CLI usage errors. Such output SHALL remain plain text without Rich box decoration or ANSI color.

#### Scenario: Invalid typed option is rejected by the framework
- **WHEN** Typer/Click rejects a value such as an out-of-range integer option before command dispatch
- **THEN** the framework usage error may be plain text
- **AND** it does not contain Rich box characters or ANSI color sequences

### Requirement: Share target and operational-root options

Commands that address Houdini directly or access global operational persistence MAY expose the following common options exactly where specified by their command contract. `--root` SHALL have one meaning throughout the CLI: override the global Houbridge operational state root for that invocation. It SHALL NOT change process cwd.

| Option | Value | Constraint | Meaning |
| --- | --- | --- | --- |
| `--port` | integer | `1..65535` | Override the configured local Houdini openport port. |
| `--root` | path | optional | Override the global Houbridge operational state root used by that invocation. |
| `--hcommand` | text/path | optional | Override the configured SideFX `hcommand` executable. |


#### Scenario: Explicit port is supplied
- **WHEN** a command accepts `--port 20001`
- **THEN** that invocation targets local port `20001`

#### Scenario: Explicit operational root is supplied
- **WHEN** a command accepts `--root E:/houbridge-state`
- **THEN** global Resource, Task, History, or overridable transient state used by that invocation resolves below `E:/houbridge-state` as defined by the owning feature
- **AND** per-Houdini target coordination remains in the fixed per-user coordination scope rather than moving with `--root`
- **AND** the caller's current working directory is unchanged

### Requirement: Format public date-time values through one shared formatter

Every public JSON field whose value is a date-time or timestamp SHALL be formatted by one shared date-time formatting function as `YYYY-MM-DDTHH:MM:SS`, for example `2026-09-08T06:58:22`. Public date-time strings SHALL omit fractional seconds and timezone suffixes.

The feature that owns the timestamp SHALL determine or convert the intended time basis before calling the formatter. Feature result builders SHALL NOT independently format public date-time values with direct `isoformat()` or `strftime()` calls.

#### Scenario: A command returns a public timestamp
- **WHEN** a logical result contains a date-time value
- **THEN** the shared formatter serializes it with second precision
- **AND** the result contains no fractional-second component or timezone suffix

### Requirement: Preserve canonical numeric lexical formatting in JSON

The shared JSON emitter SHALL preserve canonical lexical formatting required by command contracts for public numeric values. In particular, a Search score normalized as `301.278910` SHALL be emitted as the JSON number `301.278910`, not as `301.27891` and not as the JSON string `"301.278910"`.

#### Scenario: A six-decimal Search score ends in zero
- **WHEN** a Search result contains the normalized score `301.278910`
- **THEN** compact JSON emission preserves all six fractional digits
- **AND** the emitted token is a JSON number

### Requirement: Apply the common Output Policy after command payload construction

Command specifications define logical success JSON. Except for bounded Resource inspection commands, the complete logical result SHALL pass through the common Output subsystem. When the common soft inline budget requires whole-result Resource fallback, the complete logical result SHALL be persisted as a Resource and the minimal fallback SHALL be:

```json
{"resource":"<resource-id>"}
```

A command MAY preserve additional summary fields during fallback only when its command specification explicitly requires them.

#### Scenario: Search payload exceeds common inline budget
- **WHEN** a Search command constructs a result too large for direct output
- **THEN** the complete result is preserved as a Resource
- **AND** the emitted fallback is bounded according to this requirement

### Requirement: Enforce the final hard JSON boundary

After normal command-specific omission and Resource fallback, final serialized CLI JSON SHALL remain within the fixed 65536-byte hard boundary. If the final envelope itself still cannot fit, the common process boundary SHALL emit a bounded failure equivalent to:

```json
{
  "error": true,
  "code": "output_too_large",
  "message": "CLI output exceeds the hard limit and must be returned as a Resource.",
  "detail": "bytes=<serialized-bytes>; hard_limit_bytes=65536"
}
```

rather than emitting oversized JSON.

#### Scenario: Final response still exceeds hard limit
- **WHEN** the final serialized response remains above 65536 bytes after allowed Resource fallback
- **THEN** the command exits non-zero with `output_too_large`
- **AND** oversized JSON is not emitted
