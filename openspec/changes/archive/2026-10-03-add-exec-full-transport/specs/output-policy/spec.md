## MODIFIED Requirements

### Requirement: Apply one shared inline token threshold

The system SHALL estimate serialized text/JSON payload token cost through one shared token-estimator implementation owned by the common Output subsystem. Resource token metadata SHALL reuse this same estimator rather than defining a second token-counting function. The generated default inline threshold SHALL remain 256 tokens. The effective soft threshold SHALL come from the shared `[output].inline_max_tokens` configuration. Feature commands SHALL NOT own private inline-token override values. The configured threshold SHALL NOT bypass the fixed hard token ceiling. The sole command-level exception SHALL be synchronous `exec --full`, which does not select another threshold value but explicitly bypasses size-control inline decisions for its Execution result/stdout/stderr transport envelope.

#### Scenario: Resource metadata needs a token estimate
- **WHEN** Resource stores text or JSON token metadata
- **THEN** it uses the same shared token estimator as Output

#### Scenario: A result is within the inline threshold
- **WHEN** a text or JSON payload is estimated at or below the effective inline threshold
- **THEN** the common Output subsystem may permit inline presentation according to that command's response contract

#### Scenario: A result exceeds the inline threshold
- **WHEN** a text or JSON payload exceeds the effective inline threshold for a command other than synchronous `exec --full`
- **THEN** the common Output subsystem omits the large body from direct presentation
- **AND** preserves the body as a Resource when the command result can be Resource-backed

#### Scenario: Exec full bypasses the threshold rather than overriding it
- **WHEN** synchronous `exec --full` returns an Execution result/stdout/stderr body above `[output].inline_max_tokens`
- **THEN** that body remains inline under the Exec full-output contract
- **AND** the configured threshold value itself is unchanged

### Requirement: Provide Resource fallback for oversized command payloads

Every public command SHALL use the common Resource fallback path for result content that would otherwise exceed its inline output budget, except bounded Resource inspection operations whose slicing/search semantics are themselves the requested feature and synchronous `exec --full` whose requested feature is complete one-shot Execution transport. The fallback Resource SHALL be stored in `resources.db` below the configured global data directory. Feature implementations SHALL hand the complete logical result to the Output subsystem rather than truncating or inventing feature-specific fallback rules. The `exec --full` exception SHALL bypass Resource fallback rather than adding a second fallback policy.

#### Scenario: A large Search result is produced
- **WHEN** the command-specific result exceeds the inline budget
- **THEN** the complete result remains available through a Resource
- **AND** the public command response remains bounded

#### Scenario: A large OCR result is produced
- **WHEN** OCR recognition output exceeds the inline budget
- **THEN** the same common Output fallback is used rather than OCR-specific threshold code

#### Scenario: Accumulated Task output is large
- **WHEN** `task get` constructs its full logical Task state and accumulated stdout/stderr exceed the inline budget
- **THEN** the same whole-result Resource fallback is available
- **AND** Task does not introduce cursor-based output semantics solely for CLI size control

#### Scenario: Exec full requests complete transport
- **WHEN** synchronous `exec --full` builds its Execution envelope
- **THEN** no per-artifact or whole-result Resource fallback is performed solely because of output size

### Requirement: Enforce fixed absolute hard limits

Soft configuration SHALL NOT raise the fixed hard limits. The absolute inline-token ceiling SHALL remain 4096 tokens and the absolute serialized CLI JSON emission limit SHALL remain 65536 bytes for normal Output Policy paths. Synchronous `exec --full` SHALL be the only public command exception to the serialized JSON emission limit, because complete one-shot Execution transport is the requested behavior of that mode. The exception SHALL NOT change the constants, Resource inspection bounds, error-envelope policy, or limits applied to any other command.

#### Scenario: A configured inline threshold exceeds the hard token ceiling
- **WHEN** effective configuration requests more than 4096 inline tokens
- **THEN** configuration or command validation rejects the value before feature execution depends on it

#### Scenario: Final fallback JSON still exceeds the hard emission limit
- **WHEN** a normal final serialized command response would exceed 65536 bytes even after normal Resource fallback
- **THEN** the process boundary returns a bounded output-too-large failure rather than emitting the oversized JSON

#### Scenario: Exec full envelope exceeds the hard emission limit
- **WHEN** a synchronous `exec --full` Execution envelope exceeds 65536 serialized bytes
- **THEN** the complete Execution envelope is emitted
- **AND** the global hard-limit constant and behavior for every non-full path remain unchanged
