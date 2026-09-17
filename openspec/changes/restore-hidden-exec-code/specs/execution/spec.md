## ADDED Requirements

### Requirement: Execute direct source without synthetic file provenance

Synchronous Execution SHALL support invocation-local direct Python source with no caller file path. Direct source SHALL execute with `__name__ == "__main__"` and SHALL not synthesize `__file__`. When caller script arguments are present, `sys.argv[0]` SHALL be the non-file sentinel `<houbridge-code>` and following values SHALL preserve the caller arguments in order, including duplicates. The runtime MAY use a non-file diagnostic label internally for Python compilation and traceback formatting, but that label SHALL NOT be exposed as caller file provenance.

#### Scenario: Execute wrapper-provided direct source
- **WHEN** Execution receives direct source with no caller file path and caller script arguments
- **THEN** the exact source executes with `__name__ == "__main__"`
- **AND** `__file__` is absent from the caller namespace
- **AND** `sys.argv[0]` is `<houbridge-code>`
- **AND** subsequent `sys.argv` values preserve the caller arguments in order and with duplicates intact
