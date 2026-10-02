## ADDED Requirements

### Requirement: Provide hidden wrapper-only synchronous transport controls

Houbridge Exec SHALL accept hidden `--code TEXT` and `--no-history` options for trusted wrapper integrations while keeping the documented/public command surface file-backed. Both options SHALL be omitted from generated `exec --help` output. The implementation SHALL document in source that the options are hidden so AI/tool-facing command discovery continues to prefer the normal file-backed contract.

The hidden controls SHALL obey all of the following constraints:

- `--code` requires `--no-history`,
- `--no-history` MAY accompany synchronous `--file`,
- `--no-history` SHALL be rejected with `--async`,
- `--code` is mutually exclusive with `--file`,
- `--code` is synchronous-only and SHALL be rejected with `--async`,
- trailing script arguments after `--` are accepted for both file-backed and direct-source synchronous execution and preserve caller order and duplicates,
- direct source SHALL still pass normal source validation before dispatch.

#### Scenario: Wrapper executes direct source
- **WHEN** a wrapper invokes `houbridge exec --code "result = 1" --no-history`
- **THEN** Houbridge executes that exact source synchronously
- **AND** no Action History setup or entry is created for the invocation

#### Scenario: Wrapper executes a file without History
- **WHEN** a wrapper invokes `houbridge exec --file tool.py --no-history`
- **THEN** Houbridge executes `tool.py` synchronously under the normal file-backed source contract
- **AND** no Action History setup or entry is created for the invocation

#### Scenario: Hidden options are not advertised
- **WHEN** `houbridge exec --help` is rendered
- **THEN** neither `--code` nor `--no-history` appears in the help output

#### Scenario: Direct source requests asynchronous execution
- **WHEN** `--code` and `--no-history` are combined with `--async`
- **THEN** Exec rejects the invocation as a CLI usage error before Task submission

#### Scenario: Direct source omits History suppression
- **WHEN** `--code` is supplied without `--no-history`
- **THEN** Exec rejects the invocation as a CLI usage error before dispatch

#### Scenario: File History suppression requests asynchronous execution
- **WHEN** `--file` and `--no-history` are combined with `--async`
- **THEN** Exec rejects the invocation as a CLI usage error before Task submission

#### Scenario: Direct source receives script arguments
- **WHEN** arguments after `--` accompany `--code --no-history`
- **THEN** Exec preserves their order and duplicates in the direct-source invocation
- **AND** the invocation remains synchronous and History-suppressed
