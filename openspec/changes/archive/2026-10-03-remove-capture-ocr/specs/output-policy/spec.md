## MODIFIED Requirements

### Requirement: Provide Resource fallback for oversized command payloads

Every public command SHALL use the common Resource fallback path for result content that would otherwise exceed its inline output budget, except bounded Resource inspection operations whose slicing/search semantics are themselves the requested feature and synchronous `exec --full` whose requested feature is complete one-shot Execution transport. The fallback Resource SHALL be stored in `resources.db` below the configured global data directory. Feature implementations SHALL hand the complete logical result to the Output subsystem rather than truncating or inventing feature-specific fallback rules. The `exec --full` exception SHALL bypass Resource fallback rather than adding a second fallback policy.

#### Scenario: A large Search result is produced
- **WHEN** the command-specific result exceeds the inline budget
- **THEN** the complete result remains available through a Resource
- **AND** the public command response remains bounded

#### Scenario: Accumulated Task output is large
- **WHEN** `task get` constructs its full logical Task state and accumulated stdout/stderr exceed the inline budget
- **THEN** the same whole-result Resource fallback is available
- **AND** Task does not introduce cursor-based output semantics solely for CLI size control

#### Scenario: Exec full requests complete transport
- **WHEN** synchronous `exec --full` builds its Execution envelope
- **THEN** no per-artifact or whole-result Resource fallback is performed solely because of output size
