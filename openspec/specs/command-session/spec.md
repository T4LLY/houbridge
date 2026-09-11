# Session Command Specification

## Purpose

Define the public syntax, options, and JSON response contract for creating, inspecting, and selecting registered local Houdini sessions.

## Requirements

### Requirement: Expose session info

The syntax SHALL be:

```text
houbridge session info [--session INTEGER]
```

`--session` SHALL be a positive registered session number.

When `--session` is omitted, `session info` SHALL inspect all registered sessions and return the registry primary selection plus one public info object per session:

```json
{
  "primary": 3,
  "sessions": [
    {
      "session": 1,
      "port": 49152,
      "pid": 12340,
      "version": "22.0.429",
      "license": "Commercial",
      "file": "C:/project/a.hip",
      "headless": false
    },
    {
      "session": 3,
      "port": 49154,
      "pid": 18744,
      "version": "22.0.429",
      "license": "Commercial",
      "file": "C:/project/b.hip",
      "headless": false
    }
  ]
}
```

`primary` SHALL be `null` when no primary session is selected.

When `--session N` is supplied, success SHALL contain exactly the selected session's public fields plus whether it is primary:

```json
{
  "session": 3,
  "primary": true,
  "port": 49154,
  "pid": 18744,
  "version": "22.0.429",
  "license": "Commercial",
  "file": "C:/project/b.hip",
  "headless": false
}
```

`file` MAY be `null`. `headless` SHALL be a boolean describing the probed session and SHALL be `true` when Houdini reports that its UI is unavailable. `pid` is a public `session info` field. Process-incarnation identity remains internal.

#### Scenario: Read all registered sessions
- **WHEN** `houbridge session info` is invoked without `--session`
- **THEN** every registered session is inspected
- **AND** the response contains `primary` and `sessions`
- **AND** each session entry contains `session`, `port`, `pid`, `version`, `license`, `file`, and `headless`

#### Scenario: Read one registered session
- **WHEN** `houbridge session info --session 3` is invoked
- **THEN** only session `3` is inspected
- **AND** the response additionally reports whether session `3` is the current primary

#### Scenario: Read an active headless session
- **WHEN** the selected Houdini target reports that its UI is unavailable
- **THEN** `headless` is `true`
- **AND** the remaining public fields use the same schema as a GUI session

### Requirement: Expose session new

The syntax SHALL be:

```text
houbridge session new [--file PATH] [--headless] [--hcommand PATH]
```

| Option | Constraint | Behavior |
| --- | --- | --- |
| `--file PATH` | optional readable path | Launch the new Houdini process with this HIP file. |
| `--headless` | boolean flag, default false | Launch a new headless Houdini session. |
| `--hcommand PATH` | optional executable path | Override the Houdini launch executable for this invocation. It SHALL identify an executable only and SHALL NOT contain launch arguments. |

`session new` SHALL always create a new Houdini process. It SHALL NOT probe for or reuse an already-running Houdini process before launch.

Before allocating the new session number, Houbridge SHALL remove stale registry entries whose recorded PID is no longer alive. It SHALL then allocate the smallest unused positive session number. Houdini SHALL choose the TCP port by executing `openport -a`; Houbridge SHALL NOT choose or probe candidate free ports itself.

Successful creation SHALL return exactly:

```json
{
  "session": 2,
  "port": 49153,
  "pid": 18744
}
```

#### Scenario: Create the first session
- **WHEN** no Session registry has previously been created and `session new` succeeds
- **THEN** the new session number is `1`
- **AND** session `1` is automatically recorded as `primary`

#### Scenario: Create an additional session
- **WHEN** a Session registry already exists and `session new` succeeds
- **THEN** the smallest unused positive session number is assigned
- **AND** the existing primary selection is not changed

#### Scenario: Reuse a stale session number
- **WHEN** session `2` is stale and sessions `1` and `3` are live when `session new` begins
- **THEN** the stale entry is removed
- **AND** the new process is registered as session `2`

#### Scenario: Previous primary is stale
- **WHEN** stale cleanup removes the session named by `primary`
- **THEN** `primary` is unset
- **AND** the newly created session is not automatically promoted merely because no primary remains

#### Scenario: Explicit launch executable is supplied
- **WHEN** `session new --hcommand PATH` is invoked
- **THEN** that executable is used for this launch
- **AND** persistent configuration is not mutated

### Requirement: Expose session promote

The syntax SHALL be:

```text
houbridge session promote SESSION
```

`SESSION` SHALL be a positive registered live session number. Promotion SHALL set that session as the sole primary session and replace any previous primary selection.

Successful promotion SHALL return exactly:

```json
{"primary":3}
```

#### Scenario: Promote another live session
- **WHEN** session `3` is registered and live and `houbridge session promote 3` is invoked
- **THEN** registry `primary` becomes `3`
- **AND** any previous primary selection is replaced

#### Scenario: Promotion target is unavailable
- **WHEN** the requested session does not resolve to a registered live process
- **THEN** promotion fails through the common BridgeError envelope
- **AND** the previous primary selection is unchanged
