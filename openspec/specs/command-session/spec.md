# Session Command Specification

## Purpose

Define the public syntax, options, and JSON response contract for creating, attaching, detaching, inspecting, and selecting registered local Houdini sessions.

## Requirements

### Requirement: Expose session info

The syntax SHALL be:

```text
houbridge session info [--session INTEGER]
```

`--session` SHALL be a positive registered session number.

When `--session` is omitted, `session info` SHALL first apply the normal stale-cleanup rule. A process-identity read failure or port-liveness result that does not prove staleness SHALL NOT remove the entry. It SHALL then inspect all remaining registered sessions and return the registry primary selection plus one public info object per session:

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

Before allocating the new session number, Houbridge SHALL apply the normal stale-cleanup rule and remove only entries proven stale. It SHALL then allocate the smallest unused positive session number. Houdini SHALL choose the TCP port by executing `openport -a`; Houbridge SHALL NOT choose or probe candidate free ports itself.

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

#### Scenario: Previous primary is stale while another live session remains
- **WHEN** stale cleanup removes the session named by `primary`
- **AND** at least one other live session remains
- **THEN** `primary` is unset
- **AND** the newly created session is not automatically promoted merely because no primary remains

#### Scenario: Previous sessions are all stale
- **WHEN** stale cleanup removes every previously registered session before `session new` completes
- **THEN** the newly created session becomes `primary`

#### Scenario: Explicit launch executable is supplied
- **WHEN** `session new --hcommand PATH` is invoked
- **THEN** that executable is used for this launch
- **AND** persistent configuration is not mutated

### Requirement: Expose session attach

The syntax SHALL be:

```text
houbridge session attach PORT
```

`PORT` SHALL be an integer in the range `1..65535`. The target Houdini process SHALL already have a local openport. For the normal manual workflow, the user runs `openport -a -q` in that Houdini Textport and passes the printed port to `session attach`. Houbridge SHALL NOT attempt to inject `openport` into an unprepared existing process.

Before registration, Houbridge SHALL probe the supplied local port, confirm that the probed Houdini PID remains the same across validation, confirm that the requested port is present in that Houdini process's reported open ports, and capture the operating-system process incarnation used by normal Session validation. It SHALL then apply normal stale registry cleanup and allocate the smallest unused positive session number.

Successful attachment SHALL return exactly:

```json
{
  "session": 2,
  "port": 49153,
  "pid": 18744
}
```

If the same Houdini process is already registered through the same port, attachment SHALL be idempotent and return that existing session without creating another record. If the same live Houdini process is already registered through a different port, attachment SHALL fail rather than create a second Session record for one process.

The attached session SHALL become `primary` only when stale cleanup leaves no live registered sessions. If at least one live registered session remains, the existing primary selection, including `null`, SHALL be preserved.

#### Scenario: Attach a manually opened existing Houdini
- **WHEN** the user runs `openport -a -q` in an existing Houdini and invokes `houbridge session attach` with the printed port
- **THEN** Houbridge validates the port, PID, and process incarnation
- **AND** registers the existing Houdini without launching another process

#### Scenario: Attach the same target twice
- **WHEN** the same Houdini PID and port are already registered
- **THEN** `session attach` returns the existing session number
- **AND** no duplicate Session record is created

#### Scenario: Existing process is already registered through another port
- **WHEN** the probed Houdini process is already represented by a live Session record using another port
- **THEN** attachment fails through the common BridgeError envelope
- **AND** the existing Session record is not replaced or duplicated

#### Scenario: Attach while another live session remains and no primary is selected
- **WHEN** stale cleanup leaves another live registered session but `primary` is `null`
- **THEN** the attached session is registered
- **AND** `primary` remains `null`

### Requirement: Expose session detach

The syntax SHALL be:

```text
houbridge session detach SESSION
```

`SESSION` SHALL be a positive registered session number. Detachment SHALL remove the registry entry without validating or contacting the Houdini process. It SHALL NOT stop the process or close its openport.

Successful detachment SHALL return exactly:

```json
{"detached":3}
```

If the selected Session is primary, `primary` SHALL become `null`. No other Session SHALL be promoted automatically.

#### Scenario: Detach a registered session
- **WHEN** `houbridge session detach 3` is invoked for a registered Session
- **THEN** session `3` is removed from the registry
- **AND** success returns `{"detached":3}`
- **AND** Houdini is not contacted or stopped

#### Scenario: Detach the primary session
- **WHEN** session `3` is primary and is detached
- **THEN** `primary` becomes `null`
- **AND** no remaining Session becomes primary automatically

#### Scenario: Detach an unknown session
- **WHEN** the requested Session is not registered
- **THEN** detachment fails through the common BridgeError envelope
- **AND** the registry is unchanged

### Requirement: Expose graceful session stop

The syntax SHALL be:

```text
houbridge session stop SESSION
```

`SESSION` SHALL be a positive registered live session number. The command SHALL use the same stop behavior for sessions created by `session new` and sessions registered by `session attach`.

Successful graceful stop SHALL return exactly:

```json
{"stopped":3}
```

For graphical Sessions, a HIP file with unsaved changes SHALL cause the command to fail through the common BridgeError envelope without saving or exiting Houdini. For non-graphical Sessions, normal stop SHALL fail because Houdini does not provide a reliable unsaved-change state there; Houbridge SHALL NOT assume the HIP is clean. Registry removal SHALL occur only after the recorded process incarnation is confirmed exited. Normal stop SHALL NOT automatically fall back to force termination.

#### Scenario: Stop a clean session
- **WHEN** `houbridge session stop 3` targets a registered live Session with no unsaved HIP changes
- **THEN** Houdini exits normally
- **AND** session `3` is removed only after process-exit confirmation
- **AND** success returns `{"stopped":3}`

#### Scenario: Stop refuses dirty HIP
- **WHEN** `houbridge session stop 3` finds unsaved HIP changes
- **THEN** the command fails without saving the HIP file
- **AND** Houdini remains running
- **AND** session `3` remains registered

#### Scenario: Stop refuses non-graphical session when dirty state is unavailable
- **WHEN** `houbridge session stop 3` targets a non-graphical Houdini Session
- **THEN** the command fails with `session_dirty_state_unavailable` without requesting Houdini exit
- **AND** Houbridge does not infer a clean HIP from the session being newly created or named `untitled.hip`
- **AND** session `3` remains registered

#### Scenario: Graceful stop times out
- **WHEN** Houdini does not exit before the bounded graceful-stop wait expires
- **THEN** the command fails through the common BridgeError envelope
- **AND** session `3` remains registered
- **AND** no force termination is attempted automatically

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
