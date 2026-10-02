## MODIFIED Requirements

### Requirement: Record exactly six net Action Change types

The finalized Action Change vocabulary SHALL be exactly:

```text
node_created
node_deleted
node_renamed
parm_changed
input_rewired
flag_changed
```

History SHALL store execution-level net state change, not every intermediate Houdini callback. Existing nodes SHALL be compared from execution-start baseline to execution-end state. Multiple changes to the same tracked property SHALL compact to one Before/After change, and a property that returns to its original value SHALL produce no change.

A node created and deleted within the same execution SHALL produce no final Action Change. A newly created node that still exists at execution end SHALL produce `node_created` using its final path/type. For that surviving new node, parameter/input/flag changes from the earliest captured post-creation baseline to final state SHALL also be retained when non-zero; a separate `node_renamed` SHALL not be emitted because `node_created` already carries the final path. An existing node deleted during the execution SHALL produce `node_deleted`, and intermediate rename/parameter/input/flag changes for that deleted node SHALL not be retained. For a surviving renamed node, human-readable paths on its other changes SHALL use the final path while node session id remains the identity.

For each surviving tracked node, parameter comparison SHALL cover the union of parameter names in its applicable baseline and final snapshots. Each name SHALL produce one `parm_changed` if its membership differs or its present raw values differ. Absence on one side SHALL be represented by null, distinct from every present raw string including the empty string. Existing nodes SHALL use the execution-start snapshot; created nodes SHALL use their earliest captured post-creation snapshot, not an empty pre-creation parameter set. Parameters already present at creation SHALL NOT produce initialization diffs solely because the node is new. Parameter membership and values that return to the applicable baseline SHALL produce no parameter change.

#### Scenario: Parameter changes several times
- **WHEN** one parameter changes from raw value `1` to `2` to `3` during one execution
- **THEN** History stores one `parm_changed` from `1` to `3`

#### Scenario: Parameter returns to original value
- **WHEN** one parameter changes from `1` to `2` and back to `1` before execution ends
- **THEN** no `parm_changed` is stored for that parameter

#### Scenario: New node is created and deleted
- **WHEN** caller Python creates a node and deletes it before the execution ends
- **THEN** no final Action Change for that transient node is stored

#### Scenario: Existing node is deleted after intermediate edits
- **WHEN** an existing node is renamed or edited and then deleted before execution ends
- **THEN** History retains `node_deleted` for that node
- **AND** drops its intermediate rename/parameter/input/flag changes

#### Scenario: Node flag changes
- **WHEN** one of `bypass`, `display`, `render`, `template`, or `selectable_template` is available for a node and has a different value at execution end than at baseline
- **THEN** History records one `flag_changed` with boolean Before/After values

#### Scenario: Parameter is added to an existing node
- **WHEN** a parameter absent from an existing node's execution-start snapshot is present at execution end with raw value `"a"` or `""`
- **THEN** one `parm_changed` has null Before and that exact present string After

#### Scenario: Parameter is removed from an existing node
- **WHEN** a parameter present at execution start with raw value `"a"` or `""` is absent from the surviving existing node at execution end
- **THEN** one `parm_changed` has that exact present string Before and null After

#### Scenario: Parameter is added after a node's creation baseline
- **WHEN** a parameter absent from a new node's earliest captured post-creation snapshot is present at execution end with raw value `"a"` or `""`
- **THEN** the surviving node has `node_created` and one `parm_changed` with null Before and that exact present string After

#### Scenario: Parameter is removed after a node's creation baseline
- **WHEN** a parameter present in a new node's earliest captured post-creation snapshot with raw value `"a"` or `""` is absent at execution end
- **THEN** the surviving node has `node_created` and one `parm_changed` with that exact present string Before and null After

#### Scenario: Initial parameters of a created node are unchanged
- **WHEN** a new node survives with the same parameter membership and raw values as its earliest captured post-creation snapshot
- **THEN** its initial parameters produce no `parm_changed`
- **AND** `node_created` still describes the node's final path/type

#### Scenario: Added parameter is removed before finalization
- **WHEN** a parameter absent from the applicable baseline of a surviving existing or created node is added and removed before execution ends
- **THEN** no `parm_changed` is stored for that parameter

#### Scenario: Removed parameter is restored unchanged
- **WHEN** a parameter is removed and re-added on a surviving existing or created node with the same raw value as its applicable baseline, including `""`
- **THEN** no `parm_changed` is stored for that parameter

#### Scenario: Removed parameter is restored with a different raw value
- **WHEN** a parameter is removed and re-added on a surviving existing or created node with a different raw value from its applicable baseline
- **THEN** one `parm_changed` records the baseline and final strings without an intermediate null side

#### Scenario: Membership change accompanies a node rename
- **WHEN** a surviving existing or created node is renamed and has a net parameter addition or removal
- **THEN** its `parm_changed` uses the same node session id and final node path
- **AND** the existing node retains its net `node_renamed`, while the created node's final path is carried by `node_created` without a separate `node_renamed`

### Requirement: Store parameter changes as bounded unevaluated raw values

A `parm_changed` Action Change SHALL identify the node session id, final node path, parameter name, and Before/After states. For a parameter present in a snapshot, its state SHALL be the string obtained from Houdini's raw parameter value without evaluating expressions or expanding variables. For a parameter absent from that snapshot, its state SHALL be null. Null SHALL indicate only missing parameter membership on that side, not an empty raw string, an evaluation result, a deleted node, or an omitted oversized body. The recorder SHALL compare individual `hou.Parm` components so a changed tuple can be represented by the component parameter names that actually differ.

Both `before` and `after` keys SHALL be required on raw recorder parameter changes. Each raw side SHALL be a string or null, and at least one side SHALL be a string. Missing keys, both-null records, and non-string/non-null raw sides SHALL be rejected as `history_change_invalid`; public Resource omission objects SHALL NOT be accepted as raw recorder values.

Each present Before/After raw string SHALL be encoded as UTF-8 for size accounting. Values of at most 4096 bytes SHALL be stored inline as strings. A value larger than 4096 bytes SHALL not be copied into History; instead its exact UTF-8 bytes SHALL be stored as a normal Resource in the configured global `resources.db`, and the History value SHALL be the object `{"omitted":true,"resource":"<resource-id>","tokens":<estimated-tokens>}`. Resource content class and MIME SHALL be determined only by the normal Resource classifier; History SHALL NOT override them. `tokens` SHALL use the shared Resource/Output token estimator. The Resource obeys normal Resource retention; History does not extend that Resource's TTL. A null side SHALL remain null and SHALL NOT be materialized as a Resource.

#### Scenario: Expression parameter changes
- **WHEN** a parameter raw value changes from `$HIP/a.$F.bgeo` to `$HIP/b.$F.bgeo`
- **THEN** History stores those raw strings as Before/After
- **AND** does not replace them with frame-expanded filesystem paths

#### Scenario: Large raw parameter value changes
- **WHEN** one Before or After raw string exceeds 4096 UTF-8 bytes and the normal Resource classifier identifies it as plain text
- **THEN** that exact string is materialized as a `text/plain` Resource
- **AND** the History change stores `omitted:true`, the Resource id, and estimated token count instead of the large string

#### Scenario: Only one side is large
- **WHEN** one side fits inline and the other exceeds 4096 UTF-8 bytes
- **THEN** the small side remains a string
- **AND** only the large side uses the omitted Resource-reference object

#### Scenario: Present empty raw string is not absence
- **WHEN** a parameter is added with raw value `""` or a parameter with raw value `""` is removed
- **THEN** the present side remains the empty string and only the absent side is null
- **AND** neither side creates a Resource

#### Scenario: Present side is exactly at the inline bound
- **WHEN** a parameter addition or removal has a present raw string of exactly 4096 UTF-8 bytes
- **THEN** the present side remains that exact inline string and the absent side remains null

#### Scenario: Membership change has an oversized present side
- **WHEN** a parameter addition or removal has a present raw string larger than 4096 UTF-8 bytes
- **THEN** only the present side uses the normal Resource omission object with exact stored bytes and token metadata
- **AND** the missing parameter side remains null

#### Scenario: A raw parameter-change side key is missing
- **WHEN** a raw `parm_changed` record omits `before` or `after`
- **THEN** materialization rejects the record as `history_change_invalid`
- **AND** omission of a key is not interpreted as parameter absence

#### Scenario: Both raw parameter-change sides are absent
- **WHEN** a raw `parm_changed` record contains null for both `before` and `after`
- **THEN** materialization rejects the record as `history_change_invalid`

#### Scenario: A raw parameter-change side has an unsupported type
- **WHEN** either raw side is a number, boolean, array, or object, including a Resource omission object
- **THEN** materialization rejects the record as `history_change_invalid`
- **AND** it does not stringify that value into a parameter state
