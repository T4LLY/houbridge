# History Command Specification

## Purpose

Define the minimal public command surface and JSON responses for recalling and searching the selected live Houdini session's Action History.

## Requirements

### Requirement: Select current-session History through common target and root options

History commands SHALL accept the common `--port`, `--root`, and `--hcommand` options. `--port`/`--hcommand` select and probe the live Houdini session. `--root` selects the global operational root containing `history/`. History commands SHALL address only the database for the exact selected live process incarnation.

#### Scenario: Explicit operational root and port are supplied
- **WHEN** `houbridge history list --port 20001 --root E:/houbridge-state` is invoked
- **THEN** Houbridge probes local port `20001`
- **AND** resolves that process incarnation's History below `E:/houbridge-state/history/`

### Requirement: Expose History semantic/lexical search

The syntax SHALL be:

```text
houbridge history search QUERY [--top-k INTEGER] [--port INTEGER] [--root PATH] [--hcommand TEXT]
```

`QUERY` is required and non-empty. `--top-k` SHALL be `1..50` and default to `10`.

Success SHALL contain exactly one top-level field, `hits`. Each hit SHALL contain `id`, `score`, and `time`; `purpose` SHALL be included only when the entry has non-empty purpose text.

```json
{
  "hits":[
    {
      "id":42,
      "score":317.540323,
      "time":"2026-09-09T13:24:10",
      "purpose":"build preview geometry"
    }
  ]
}
```

`score` SHALL use the shared Search score formatter and `time` SHALL use the shared public date-time formatter.

#### Scenario: No current-session action matches
- **WHEN** History search returns no candidate
- **THEN** success is `{"hits":[]}`

#### Scenario: Matching entry has no purpose
- **WHEN** an entry ranks but has no purpose text
- **THEN** its hit omits `purpose`

### Requirement: Expose one complete Action History entry

The syntax SHALL be:

```text
houbridge history get HISTORY_ID [--port INTEGER] [--root PATH] [--hcommand TEXT]
```

`HISTORY_ID` is a required positive session-local integer. Success SHALL return the complete public Action History entry. The returned `root` field is the absolute cwd/origin root captured for the execution and is independent of the command's `--root` operational-storage option. `purpose` SHALL be omitted when absent. Internal source hash, embedding vectors, embedding profile, FTS data, and session-key metadata SHALL not be emitted.

A parameter-change example is:

```json
{
  "id":42,
  "time":"2026-09-09T13:24:10",
  "status":"completed",
  "root":"E:/project",
  "file":".houbridge/python/build.py",
  "args":["--quality","high"],
  "purpose":"build preview geometry",
  "changes":[
    {
      "type":"parm_changed",
      "node":417,
      "path":"/obj/geo1/box1",
      "parm":"sizex",
      "before":"1",
      "after":"2"
    }
  ]
}
```

The five public Action Change shapes SHALL be:

```json
{"type":"node_created","node":421,"before":null,"after":{"path":"/obj/geo1/noise1","node_type":"attribnoise"}}
{"type":"node_deleted","node":421,"before":{"path":"/obj/geo1/noise1","node_type":"attribnoise"},"after":null}
{"type":"node_renamed","node":417,"before":"/obj/geo1/box1","after":"/obj/geo1/box2"}
{"type":"parm_changed","node":417,"path":"/obj/geo1/box2","parm":"sizex","before":"1","after":"2"}
{"type":"input_rewired","node":417,"path":"/obj/geo1/box2","input":0,"before":{"node":416,"path":"/obj/geo1/grid1","output":0},"after":null}
```

For `input_rewired`, either connection state MAY be `null`; a non-null connection object SHALL contain exactly `node`, `path`, and `output`.

#### Scenario: Entry has no tracked changes
- **WHEN** a recorded execution changed no tracked Action state
- **THEN** `changes` is an empty array

#### Scenario: Entry is a failed Python action
- **WHEN** the recorded caller Python raised after starting
- **THEN** `status` is `failed`
- **AND** the entry still exposes its finalized Action Changes

### Requirement: Expose chronological History list

The syntax SHALL be:

```text
houbridge history list [--limit INTEGER] [--port INTEGER] [--root PATH] [--hcommand TEXT]
```

`--limit` SHALL be a positive integer and default to `20`. Entries SHALL be ordered newest first. Each list entry SHALL contain exactly `id`, `time`, `status`, and `file`, plus `purpose` only when non-empty.

```json
{
  "entries":[
    {
      "id":44,
      "time":"2026-09-09T13:31:02",
      "status":"completed",
      "file":".houbridge/python/render.py",
      "purpose":"update render settings"
    }
  ]
}
```

#### Scenario: Current session has no History
- **WHEN** no entry exists for the selected live session
- **THEN** success is `{"entries":[]}`

### Requirement: Apply the common Output Policy to History results

History search, get, and list SHALL construct their complete logical JSON and pass it through the common Output Policy. When whole-result Resource fallback is required, the Resource SHALL be stored in the effective global `resources.db` and the emitted fallback SHALL follow the common minimal Resource response.

#### Scenario: One History get contains many Action Changes
- **WHEN** the complete logical entry exceeds the common inline budget
- **THEN** the complete History response is preserved as a Resource
- **AND** the final CLI response uses the common Resource fallback contract

### Requirement: Use the shared error envelope for History failures

Unknown History ids, invalid ids, invalid query/limit values, selected-session probe failures, and History database failures SHALL use the common BridgeError JSON envelope.

#### Scenario: History id is unknown in the current session
- **WHEN** `history get 999999` cannot resolve that id
- **THEN** the command exits with status `1`
- **AND** emits the common `error/code/message[/detail]` shape
