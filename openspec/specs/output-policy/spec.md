# Output Policy Specification

## Purpose

Define the single cross-cutting output-budget mechanism used by every public command. Command-specific JSON field schemas are specified separately.

## Requirements

### Requirement: Apply one shared inline token threshold

The system SHALL estimate serialized text/JSON payload token cost through one shared token-estimator implementation owned by the common Output subsystem. Resource token metadata SHALL reuse this same estimator rather than defining a second token-counting function. The generated default inline threshold SHALL remain 256 tokens. The effective soft threshold SHALL come from the shared `[output].inline_max_tokens` configuration. Feature commands SHALL NOT own private inline-token override options. The configured threshold SHALL NOT bypass the fixed hard token ceiling.

#### Scenario: Resource metadata needs a token estimate
- **WHEN** Resource stores text or JSON token metadata
- **THEN** it uses the same shared token estimator as Output

#### Scenario: A result is within the inline threshold
- **WHEN** a text or JSON payload is estimated at or below the effective inline threshold
- **THEN** the common Output subsystem may permit inline presentation according to that command's response contract

#### Scenario: A result exceeds the inline threshold
- **WHEN** a text or JSON payload exceeds the effective inline threshold
- **THEN** the common Output subsystem omits the large body from direct presentation
- **AND** preserves the body as a Resource when the command result can be Resource-backed

### Requirement: Provide Resource fallback for oversized command payloads

Every public command SHALL use the common Resource fallback path for result content that would otherwise exceed its inline output budget. The fallback Resource SHALL be stored in `resources.db` below the invocation's effective global operational root. Feature implementations SHALL hand the complete logical result to the Output subsystem rather than truncating or inventing feature-specific fallback rules, except for bounded Resource inspection operations whose slicing/search semantics are themselves the requested feature.

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

### Requirement: Enforce fixed absolute hard limits

Soft configuration SHALL NOT raise the fixed hard limits. The absolute inline-token ceiling SHALL remain 4096 tokens and the absolute serialized CLI JSON emission limit SHALL remain 65536 bytes.

#### Scenario: A configured inline threshold exceeds the hard token ceiling
- **WHEN** effective configuration requests more than 4096 inline tokens
- **THEN** configuration or command validation rejects the value before feature execution depends on it

#### Scenario: Final fallback JSON still exceeds the hard emission limit
- **WHEN** the final serialized command response would exceed 65536 bytes even after normal Resource fallback
- **THEN** the process boundary returns a bounded output-too-large failure rather than emitting the oversized JSON

### Requirement: Keep Resource inspection bounded independently

Resource inspection SHALL retain fixed hard bounds needed to inspect oversized Resources safely. A single Resource slice SHALL request and return at most 16384 UTF-8 bytes, and one Resource search response SHALL expose at most 100 hits regardless of a larger configured value.

#### Scenario: Slice exceeds its hard maximum
- **WHEN** Resource inspection requests a slice larger than 16384
- **THEN** the request is rejected before the Resource body is returned

#### Scenario: Search limit exceeds its hard maximum
- **WHEN** Resource inspection is configured or constructed with a search limit above 100
- **THEN** one Resource search operation still returns no more than 100 hits

### Requirement: Avoid duplicate output-policy implementations

The token estimator, inline decision, Resource fallback decision, and final hard-emission guard SHALL each have one owning implementation path shared by commands.

#### Scenario: A new command is added
- **WHEN** a new public command returns structured data
- **THEN** it uses the common Output subsystem
- **AND** it does not add another local `if token_count > ...` presentation policy
