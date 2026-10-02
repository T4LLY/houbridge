## MODIFIED Requirements

### Requirement: Expose one complete Action History entry

The syntax SHALL be:

```text
houbridge history get HISTORY_ID [--session INTEGER]
```

`HISTORY_ID` is a required positive session-local integer. Success SHALL return the complete public Action History entry. The returned `file` SHALL be the normalized absolute path of the executed Python file captured for the action. The returned `cwd` field is the normalized absolute current working directory captured when the execution was submitted. `purpose` SHALL be omitted when absent. Internal source hash, embedding vectors, embedding profile, FTS data, and session-key metadata SHALL not be emitted.

A parameter-change example is:

```json
{
  "id":42,
  "time":"2026-09-09T13:24:10",
  "status":"completed",
  "cwd":"E:/project",
  "file":"E:/project/.houbridge/python/build.py",
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

The six public Action Change shapes SHALL be:

```json
[
  {"type":"node_created","node":421,"before":null,"after":{"path":"/obj/geo1/noise1","node_type":"attribnoise"}},
  {"type":"node_deleted","node":421,"before":{"path":"/obj/geo1/noise1","node_type":"attribnoise"},"after":null},
  {"type":"node_renamed","node":417,"before":"/obj/geo1/box1","after":"/obj/geo1/box2"},
  {"type":"parm_changed","node":417,"path":"/obj/geo1/box2","parm":"sizex","before":"1","after":"2"},
  {"type":"input_rewired","node":417,"path":"/obj/geo1/box2","input":0,"before":{"node":416,"path":"/obj/geo1/grid1","output":0},"after":null},
  {"type":"flag_changed","node":417,"path":"/obj/geo1/box2","flag":"bypass","before":false,"after":true}
]
```

For `input_rewired`, either connection state MAY be `null`; a non-null connection object SHALL contain exactly `node`, `path`, and `output`. `flag_changed` SHALL use one of the supported flags available for that node: `bypass`, `display`, `render`, `template`, or `selectable_template`.

Each `parm_changed` SHALL contain exactly `type`, `node`, `path`, `parm`, `before`, and `after`. Both side keys SHALL be present. Each side SHALL be an unevaluated raw string, JSON null indicating that the parameter was absent from that side's snapshot, or the existing Resource omission object for an oversized present string. Empty strings SHALL denote present empty raw values, not absence. Both sides SHALL NOT be null in a valid changed-parameter record. Parameter additions SHALL use null `before`; removals SHALL use null `after`. Clients may receive null on the missing side without a compatibility mode or absence-specific fallback representation.

When one present value exceeded the History inline raw-value bound, that side SHALL instead use exactly:

```json
{"omitted":true,"resource":"large-parm-value-000","tokens":9138}
```

The `resource` may later expire under normal Resource retention; `omitted:true` and `tokens` remain part of the session History entry.

#### Scenario: Entry has no tracked changes
- **WHEN** a recorded execution changed no tracked Action state
- **THEN** `changes` is an empty array

#### Scenario: Entry is a failed Python action
- **WHEN** the recorded caller Python raised after starting
- **THEN** `status` is `failed`
- **AND** the entry still exposes its finalized Action Changes

#### Scenario: Entry includes a parameter addition
- **WHEN** an entry contains an added parameter with inline raw value `"a"` or `""`
- **THEN** `history get` exposes its `parm_changed` with `before:null` and `after` equal to that exact present string
- **AND** the change contains exactly the six required parameter-change keys

#### Scenario: Entry includes a parameter removal
- **WHEN** an entry contains a removed parameter whose baseline inline raw value was `"a"` or `""`
- **THEN** `history get` exposes its `parm_changed` with `before` equal to that exact present string and `after:null`
- **AND** the change contains exactly the six required parameter-change keys

#### Scenario: Entry includes a membership change with an oversized value
- **WHEN** the present side of a recorded parameter addition or removal exceeded 4096 UTF-8 bytes
- **THEN** `history get` exposes that side as the existing object containing exactly `omitted`, `resource`, and `tokens`
- **AND** exposes the absent side as null with both side keys retained

#### Scenario: Entry includes an ordinary parameter-value edit
- **WHEN** a parameter was present in both snapshots and its inline raw value changed from `"1"` to `"2"`
- **THEN** `history get` retains the existing string Before/After representation
