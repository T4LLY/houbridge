# Task Command Specification

## Purpose

Define the minimal public command surface and JSON responses for observing and resetting asynchronous Tasks.

## Requirements

### Requirement: Select Task operational persistence with the common root option

`task get`, `task list`, and `task reset` SHALL accept `--root ROOT`. When omitted, they SHALL use the configured global operational root. When supplied, they SHALL resolve `<ROOT>/tasks.db` and any Task completion Resource references against `<ROOT>/resources.db` without changing process cwd.

#### Scenario: Read Tasks from an explicit operational root
- **WHEN** `houbridge task list --root E:/houbridge-state` is invoked
- **THEN** Task lookup uses `E:/houbridge-state/tasks.db`
- **AND** the caller's current working directory is unchanged

### Requirement: Expose Task get

The syntax SHALL be:

```text
houbridge task get TASK_ID [--root ROOT]
```

A queued Task SHALL return:

```json
{
  "id":"geometry-build-cache-000",
  "status":"queued",
  "file":"E:/project/.houbridge/python/build.py",
  "args":["--quality","high"]
}
```

A running Task SHALL return its complete accumulated stdout/stderr available at read time:

```json
{
  "id":"geometry-build-cache-000",
  "status":"running",
  "file":"E:/project/.houbridge/python/build.py",
  "args":["--quality","high"],
  "stdout":"10%\n20%\n",
  "stderr":""
}
```

A completed Task SHALL additionally return the completion Resource id:

```json
{
  "id":"geometry-build-cache-000",
  "status":"completed",
  "file":"E:/project/.houbridge/python/build.py",
  "args":["--quality","high"],
  "stdout":"10%\n20%\n50%\n100%\n",
  "stderr":"",
  "resource":"RESOURCE_ID"
}
```

A Python-failed Task SHALL retain produced streams:

```json
{
  "id":"geometry-build-cache-000",
  "status":"failed",
  "file":"E:/project/.houbridge/python/build.py",
  "args":[],
  "stdout":"10%\n20%\n",
  "stderr":"Traceback ..."
}
```

When a Houbridge/Task Runtime failure exists, `task get` SHALL additionally contain a nested runtime error object:

```json
{
  "id":"geometry-build-cache-000",
  "status":"failed",
  "file":"E:/project/.houbridge/python/build.py",
  "args":[],
  "stdout":"10%\n",
  "stderr":"",
  "error":{
    "code":"task_target_changed",
    "message":"The target Houdini process changed before execution."
  }
}
```

Retrieving an existing `failed` Task is itself a successful read operation and SHALL exit with status `0`. The complete logical object SHALL pass through the common Output Policy. When whole-result Output fallback occurs, the emitted one-field `{"resource":"..."}` object refers to the Resource containing the complete Task-get response; inside that preserved logical response, a completed Task's own `resource` field continues to refer to its completion stdout/stderr Resource.

#### Scenario: Read queued Task
- **WHEN** `task get` is invoked before caller Python starts
- **THEN** the Task reports `queued`, its normalized absolute `file`, and `args`
- **AND** `stdout`, `stderr`, and `resource` are omitted

#### Scenario: Read running output
- **WHEN** `task get` is invoked while a Task is running
- **THEN** stdout/stderr contain all accumulated Task stream text available at that read
- **AND** no cursor or consumed offset is required

#### Scenario: Read completed Resource reference
- **WHEN** the Task is completed
- **THEN** `resource` is returned
- **AND** the Resource is resolved from the same effective global operational root when inspected later

#### Scenario: Read Task with runtime failure
- **WHEN** a Task failed because of Houbridge runtime state rather than a Python exception
- **THEN** the nested `error` object carries the runtime failure
- **AND** `stderr` remains the caller Python stderr stream

### Requirement: Expose Task list

The syntax SHALL be:

```text
houbridge task list [--root ROOT]
```

Success SHALL use:

```json
{
  "tasks":[
    {
      "id":"geometry-build-cache-000",
      "status":"running",
      "file":"E:/project/.houbridge/python/build.py",
      "args":["--quality","high"]
    }
  ]
}
```

Each listed Task SHALL contain exactly `id`, `status`, `file`, and `args`. `file` SHALL be the normalized absolute path captured at submission. Entries SHALL be ordered by `created_at` descending, with a stable Task id tie-breaker when required. Internal PID, port, origin root, output chunks, runtime ownership, and semantic ordinal data SHALL not be included in list entries.

#### Scenario: No Task is retained
- **WHEN** no non-expired Task exists
- **THEN** success returns `{"tasks":[]}`

### Requirement: Expose Task reset

The syntax SHALL be:

```text
houbridge task reset [--root ROOT]
```

A successful reset SHALL emit `{}`. Reset availability and state-clearing behavior SHALL follow the Task feature specification.

#### Scenario: Reset succeeds
- **WHEN** all retained Tasks are terminal and reset completes
- **THEN** the command exits with status `0`
- **AND** emits `{}`

#### Scenario: Reset is blocked by active work
- **WHEN** a `queued` or `running` Task exists
- **THEN** the command exits with status `1`
- **AND** emits the common BridgeError envelope

### Requirement: Trigger lazy Task Runtime recovery from Task commands

Before returning normal Task state, `task get`, `task list`, and `task reset` SHALL participate in the Task feature's stale-runtime ownership check. A read command MAY therefore awaken a replacement runtime when recoverable queued/running state exists. This internal recovery behavior SHALL not add fields to the public Task JSON schema.

#### Scenario: Task list finds stale runtime ownership
- **WHEN** `task list` observes recoverable active work without a valid runtime owner
- **THEN** it ensures replacement runtime activation according to the Task feature contract
- **AND** it still returns the normal Task list schema

### Requirement: Use the shared error envelope for Task lookup and operation failures

Unknown Task ids, invalid Task ids, reset conflicts, Task database failures, and other handled Task command failures SHALL use the common BridgeError JSON envelope.

#### Scenario: Task does not exist
- **WHEN** `task get missing-task` cannot resolve the Task id
- **THEN** the command exits with status `1`
- **AND** emits the common `error/code/message[/detail]` JSON shape
