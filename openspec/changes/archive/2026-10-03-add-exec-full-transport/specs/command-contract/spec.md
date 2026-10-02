## MODIFIED Requirements

### Requirement: Apply the common Output Policy after command payload construction

Command specifications define logical success JSON. Except for bounded Resource inspection commands and the explicitly unbounded synchronous `exec --full` Execution transport mode, the complete logical result SHALL pass through the common Output subsystem. When the common soft inline budget requires whole-result Resource fallback, the complete logical result SHALL be persisted as a Resource and the minimal fallback SHALL be:

```json
{"resource":"<resource-id>"}
```

A command MAY preserve additional summary fields during fallback only when its command specification explicitly requires them. `exec --full` SHALL not define another Resource fallback shape; it SHALL bypass whole-result fallback and emit its complete Execution envelope with the shared canonical JSON serializer.

#### Scenario: Search payload exceeds common inline budget
- **WHEN** a Search command constructs a result too large for direct output
- **THEN** the complete result is preserved as a Resource
- **AND** the emitted fallback is bounded according to this requirement

#### Scenario: Exec full bypasses whole-result fallback
- **WHEN** synchronous `exec --full` constructs a complete Execution envelope above the common inline budget
- **THEN** that envelope is emitted directly according to the command-exec full-output contract
- **AND** it is not replaced by a whole-result Resource solely because of size

### Requirement: Enforce the final hard JSON boundary

After normal command-specific omission and Resource fallback, final serialized CLI JSON SHALL remain within the fixed 65536-byte hard boundary except for the synchronous `exec --full` Execution envelope explicitly defined by the Exec command contract. If a normal final envelope itself still cannot fit, the common process boundary SHALL emit a bounded failure equivalent to:

```json
{
  "error": true,
  "code": "output_too_large",
  "message": "CLI output exceeds the hard limit and must be returned as a Resource.",
  "detail": "bytes=<serialized-bytes>; hard_limit_bytes=65536"
}
```

rather than emitting oversized JSON. The `exec --full` exception SHALL not apply to `resource get --full` or any other command.

#### Scenario: Final response still exceeds hard limit
- **WHEN** a normal final serialized response remains above 65536 bytes after allowed Resource fallback
- **THEN** the command exits non-zero with `output_too_large`
- **AND** oversized JSON is not emitted

#### Scenario: Exec full response exceeds hard limit
- **WHEN** the complete synchronous `exec --full` Execution envelope exceeds 65536 serialized bytes
- **THEN** the command emits that complete envelope using the shared canonical JSON serializer
- **AND** does not return `output_too_large` solely because of the envelope size
