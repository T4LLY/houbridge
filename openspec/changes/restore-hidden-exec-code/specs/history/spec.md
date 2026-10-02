## MODIFIED Requirements

### Requirement: Make Action History recording configurable and enabled by default

The generated configuration SHALL use `[history].enabled = true`. The effective setting for an Exec invocation SHALL determine whether that execution initializes Action Change capture and contributes a History entry. Disabling History through configuration SHALL skip Action recorder setup, History source embedding work, and History entry creation for that invocation. Hidden synchronous `exec --no-history` SHALL additionally suppress History for that invocation even when `[history].enabled = true`. Hidden direct-source `exec --code` SHALL require this override; synchronous file-backed Exec MAY opt into it.

History read commands MAY inspect an already-existing current-session database regardless of whether recording is disabled for the caller's current working directory or for one invocation.

#### Scenario: Recording is enabled
- **WHEN** managed file-backed Python actually starts with effective `[history].enabled = true` and no invocation override disables recording
- **THEN** the execution is eligible for Action History finalization

#### Scenario: Recording is disabled by configuration
- **WHEN** managed Python runs with effective `[history].enabled = false`
- **THEN** its execution proceeds without History capture or History embedding work

#### Scenario: Wrapper direct source suppresses History
- **WHEN** hidden `exec --code` runs with its required `--no-history` override while `[history].enabled = true`
- **THEN** the execution proceeds without History capture, source embedding, or History entry creation

#### Scenario: Wrapper file execution suppresses History
- **WHEN** synchronous hidden `exec --file ... --no-history` runs while `[history].enabled = true`
- **THEN** the file executes normally without History capture, source embedding, or History entry creation
