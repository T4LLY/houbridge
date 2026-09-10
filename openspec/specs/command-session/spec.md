# Session Command Specification

## Purpose

Define the public syntax, options, and JSON response contract for inspecting or starting a local Houdini session.

## Requirements

### Requirement: Expose session info

The syntax SHALL be:

```text
houbridge session info [--port INTEGER] [--root PATH] [--hcommand TEXT]
```

`--port` SHALL accept `1..65535`. `--root` and `--hcommand` follow the common runtime contract.

A successful response SHALL contain exactly the public session fields:

```json
{
  "port": 18888,
  "version": "22.0.429",
  "license": "Commercial",
  "file": "C:/project/test.hip",
  "headless": false
}
```

`file` MAY be `null`. `headless` SHALL be a boolean describing the probed session and SHALL be `true` when Houdini reports that its UI is unavailable. Internal target identity SHALL NOT be emitted.

#### Scenario: Read an active GUI session
- **WHEN** the local Houdini target responds to the session probe with UI available
- **THEN** `port`, `version`, `license`, `file`, and `headless` are emitted
- **AND** `headless` is `false`
- **AND** `target_id` is not emitted

#### Scenario: Read an active headless session
- **WHEN** the local Houdini target responds to the session probe with UI unavailable
- **THEN** `headless` is `true`
- **AND** the remaining public fields use the same schema as a GUI session

### Requirement: Expose session start

The syntax SHALL be:

```text
houbridge session start [--file PATH] [--headless] [--executable TEXT] [--port INTEGER] [--root PATH] [--hcommand TEXT]
```

| Option | Constraint | Behavior |
| --- | --- | --- |
| `--file PATH` | optional path | HIP file validated and loaded only when a new Houdini process must be launched. |
| `--headless` | boolean flag, default false | Launch a headless Houdini session when a new process must be started. |
| `--executable TEXT` | optional | Explicit Houdini executable/tool selector for the selected launch mode; automatic discovery is used when omitted. |
| `--port INTEGER` | `1..65535` | Target/open port override. |
| `--root PATH` | optional | Common runtime option. |
| `--hcommand TEXT` | optional | Common runtime option. |

Session start SHALL retain its reuse-first behavior. `--file` and `--headless` are launch-only options. `--file` existence/readability validation SHALL occur only after the initial reuse probe determines that a new process must be launched. If a usable session is already reachable, it SHALL be reused and its probed `headless` value SHALL be returned; the requested launch mode SHALL NOT replace the running process. When no usable session exists on the selected port, Houbridge SHALL launch the selected mode and SHALL report success only after the selected openport is reachable and the session probe succeeds.

If a usable session already exists, success SHALL be:

```json
{
  "launched": false,
  "session": {
    "port": 18888,
    "version": "22.0.429",
    "license": "Commercial",
    "file": "C:/project/test.hip",
    "headless": false
  }
}
```

If Houbridge launches Houdini, success SHALL additionally include `pid` and set `launched` true:

```json
{
  "launched": true,
  "pid": 12345,
  "session": {
    "port": 18888,
    "version": "22.0.429",
    "license": "Commercial",
    "file": "C:/project/test.hip",
    "headless": false
  }
}
```

#### Scenario: Existing session is reused
- **WHEN** session probing succeeds before a new process is launched
- **THEN** `launched` is `false`
- **AND** `pid` is omitted
- **AND** `session.headless` reflects the existing process rather than the requested launch mode

#### Scenario: New GUI process is launched
- **WHEN** no usable session exists and startup succeeds without `--headless`
- **THEN** `launched` is `true`
- **AND** `pid` contains the launched process id
- **AND** `session.headless` is `false`
- **AND** `session` contains the same public fields as `session info`

#### Scenario: New headless process is launched
- **WHEN** no usable session exists and startup succeeds with `--headless`
- **THEN** `launched` is `true`
- **AND** `pid` contains the launched process id
- **AND** `session.headless` is `true`
- **AND** `session` contains the same public fields as `session info`

#### Scenario: New Houdini process is launched with a HIP file
- **WHEN** no usable session exists and `--file C:/project/test.hip` is supplied
- **THEN** the launched Houdini process opens that file
- **AND** the successful session probe reports the loaded HIP through `session.file`

#### Scenario: Invalid launch file is supplied while a session is already reachable
- **WHEN** `--file` names a missing/unreadable path but the selected session probe succeeds
- **THEN** the existing session is reused
- **AND** launch-file validation is not performed because no launch is required

#### Scenario: Launch-only options are supplied while a session is already reachable
- **WHEN** `--file` or `--headless` is supplied and session probing succeeds before launch
- **THEN** the existing Houdini process is reused
- **AND** the running scene and process mode are not replaced by the launch-only options
