## MODIFIED Requirements

### Requirement: Preserve the file execution namespace contract

User code SHALL execute with `__name__ == "__main__"` and SHALL expose the caller-supplied file path as `__file__`. For synchronous file-backed Execution, Houbridge SHALL resolve the caller file's parent directory against the invocation's frozen origin cwd, temporarily prepend that absolute directory to Houdini `sys.path` while caller Python runs, and restore the previous `sys.path` after execution whether the source succeeds or raises. This import-root behavior SHALL NOT rewrite the caller-visible `__file__` value.

#### Scenario: Execute a caller-side Python file
- **WHEN** Execution is given a file source path and its already-read source
- **THEN** Houdini executes that source with `__name__` set to `__main__`
- **AND** `__file__` is set to the supplied file path

#### Scenario: Caller file imports a sibling helper
- **WHEN** synchronous file execution imports a module located beside the caller file
- **THEN** the caller file's resolved parent directory is first on `sys.path` while caller Python runs
- **AND** the sibling import can resolve without wrapper-specific path manipulation

#### Scenario: Caller supplied a relative file path
- **WHEN** synchronous execution was prepared from a relative caller path
- **THEN** its import root is resolved relative to the invocation origin cwd
- **AND** it does not depend on Houdini's current working directory

#### Scenario: Caller Python raises after import-root setup
- **WHEN** synchronous file execution temporarily prepends the caller-file directory and caller Python raises
- **THEN** Houdini's prior `sys.path` is restored in the execution cleanup path
