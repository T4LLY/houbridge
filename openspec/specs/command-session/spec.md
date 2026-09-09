# Session Command Specification

## Purpose

Define the public syntax, options, and JSON response contract for inspecting or starting the local Houdini session.

## Requirements

### Requirement: Expose session info

The syntax SHALL be:

```text
houbridge session info [--port INTEGER] [--root PATH] [--hcommand TEXT]
```

`--port` SHALL accept `1..65535`. `--root` and `--hcommand` follow the common runtime contract. No `--host` option SHALL exist.

A successful response SHALL contain exactly the public session fields:

```json
{
  "host": "localhost",
  "port": 18888,
  "application_version": "22.0.429",
  "license_category": "Commercial",
  "hip_file": "C:/project/test.hip"
}
```

`hip_file` MAY be `null`. Internal target identity SHALL NOT be emitted.

#### Scenario: Read an active session
- **WHEN** the local Houdini target responds to the session probe
- **THEN** `host`, `port`, `application_version`, `license_category`, and `hip_file` are emitted
- **AND** `target_id` is not emitted

### Requirement: Expose session start

The syntax SHALL be:

```text
houbridge session start [--file PATH] [--executable TEXT] [--port INTEGER] [--root PATH] [--hcommand TEXT]
```

| Option | Constraint | Behavior |
| --- | --- | --- |
| `--file PATH` | optional existing readable file | HIP file to load when a new Houdini process is launched. |
| `--executable TEXT` | optional | Explicit Houdini GUI executable; automatic discovery is used when omitted. |
| `--port INTEGER` | `1..65535` | Target/open port override. |
| `--root PATH` | optional | Common runtime option. |
| `--hcommand TEXT` | optional | Common runtime option. |

Session start SHALL retain its reuse-first behavior. `--file` is a launch-only option: when no usable session exists on the selected port, Houbridge SHALL launch Houdini with that HIP file loaded and SHALL report success only after the selected openport is reachable and the session probe succeeds. If a usable session is already reachable, it SHALL be reused and `--file` SHALL NOT load or replace the scene in that running process.

If a usable session already exists and no file conflict applies, success SHALL be:

```json
{
  "launched": false,
  "session": {
    "host": "localhost",
    "port": 18888,
    "application_version": "22.0.429",
    "license_category": "Commercial",
    "hip_file": "C:/project/test.hip"
  }
}
```

If Houbridge launches Houdini, success SHALL additionally include `pid` and set `launched` true:

```json
{
  "launched": true,
  "pid": 12345,
  "session": {
    "host": "localhost",
    "port": 18888,
    "application_version": "22.0.429",
    "license_category": "Commercial",
    "hip_file": "C:/project/test.hip"
  }
}
```

#### Scenario: Existing session is reused
- **WHEN** session probing succeeds before a new process is launched
- **THEN** `launched` is `false`
- **AND** `pid` is omitted

#### Scenario: New Houdini process is launched without a file
- **WHEN** no usable session exists and startup succeeds without `--file`
- **THEN** `launched` is `true`
- **AND** `pid` contains the launched process id
- **AND** `session` contains the same public fields as `session info`

#### Scenario: New Houdini process is launched with a HIP file
- **WHEN** no usable session exists and `--file C:/project/test.hip` is supplied
- **THEN** the launched Houdini process opens that file
- **AND** the successful session probe reports the loaded HIP through `session.hip_file`

#### Scenario: File option is supplied while a session is already reachable
- **WHEN** `--file` is supplied and session probing succeeds before launch
- **THEN** the existing Houdini process is reused
- **AND** the running scene is not replaced by the requested file
