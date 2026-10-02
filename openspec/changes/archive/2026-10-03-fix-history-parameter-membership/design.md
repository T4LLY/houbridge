## Context

See `proposal.md` for motivation and approval. Preparation is anchored to verified HEAD `70839fc` and the current architecture/configuration and History specifications.

- The Houdini-injected `ActionRecorder` captures raw strings per component, marks existing nodes dirty via callbacks, and captures new nodes at `ChildCreated`. `_diff_existing` and `_diff_created` share `_parm_changes`, whose `old.keys() & new.keys()` excludes one-sided names.
- Host `src/houbridge/history/changes.py` enforces exact change keys, currently validates both parameter sides as strings, bounds each at 4096 UTF-8 bytes through `ResourceStore`, and serializes `HistoryRawValue` as a string or `OmittedRawValue`.
- `houdini/scripts/history/execution.py` publishes JSON capture; `history/invocation.py` validates the capture envelope and materializes changes before committing. Session-local `history_changes.payload_json` stores ordinary JSON, and `HistoryReader` decodes and returns those dictionaries without reconstructing parameter values.
- `history/search.py` projects stored scalar context deterministically. `_append_scalars` already skips null while retaining field keys and parameter names; it does not fetch omitted Resource bodies. Dense retrieval embeds executed source only.
- Existing tests cover six change shapes, compaction, final paths, node deletion/transience, scene reset, 4096-byte inclusion, normal Resource classification (including JSON-shaped strings), and History read/search behavior. The parent's `D:/Temp/opencode/hb02_70839fc_repro.py` supplies eight membership witnesses plus six before-change controls.

## Goals / Non-Goals

**Goals:** Make snapshot membership differences survive recorder capture, host validation/materialization, session persistence, public read, and existing lexical projection using the approved absence contract.

**Non-Goals:** Parameter-template/type metadata, new change types, event-subscription expansion, compatibility modes, new dependencies, or SQL-schema changes. The separate `restore-hidden-exec-code` change remains separately owned.

## Residual Event-Coverage Limitation

This change does not verify native Houdini event delivery. The recorder currently subscribes to `ParmTupleChanged`, while Houdini [documents `SpareParmTemplatesChanged`](https://www.sidefx.com/docs/houdini/hom/hou/nodeEventType.html) for spare-parameter add/remove. Current evidence does not establish native delivery for spare or multiparm membership changes, nor prove that multiparm delivery is silent. Fake recorder tests emit `ParmTupleChanged` as an explicit callback-delivery assumption only. Therefore, do not claim all spare-parameter or multiparm membership changes are captured. Native event coverage and any subscription expansion are deferred follow-up work, consistent with the non-goal above.

## Decisions

### 1. Compare presence and raw values over the key union

Keep `_parm_changes` as the common implementation for existing and created nodes. Iterate sorted union keys, preserve a missing side as Python `None`, and compare that absence-aware state with the present raw string. A string is always present, including `""` or literal text `"null"`; do not stringify absence or use truthiness to detect it. The current intersection cannot express membership changes, and an empty-string sentinel would collapse real empty values.

Existing nodes retain their execution-start baseline; created nodes retain the earliest captured post-creation snapshot. A created node is not compared against an artificial empty parameter set. Added-then-removed names and removed-then-restored identical strings produce no net record. Removed-then-restored different strings produce one string-to-string record. Existing deletion still short-circuits property diffs, transient new nodes remain suppressed, and final path/session-id handling stays in the existing node compaction paths.

### 2. Distinguish raw input validation from public materialization

Raw recorder sides accept only `str | None`. Preserve `_exact_keys` for the six-field parameter record, require both sides, and reject both-null records and other raw types through the existing `history_change_invalid` error. This contract does not authorize raw Resource-reference objects.

Extend the materialized `HistoryRawValue`/parameter-side types to `str | None | OmittedRawValue`. A null side passes through to JSON null without byte accounting or Resource creation. Present strings use the existing UTF-8 bound, normal classifier, semantic alias/token metadata, and normal Resource retention. `_raw_value_payload` must explicitly preserve `None`. The public omission object denotes a present oversized string; it cannot denote parameter absence.

### 3. Reuse the existing storage, read, search, and Output boundaries

Recorder snapshots remain invocation-local live-Houdini state. Host History owns validation and session-scoped persistence; oversized bytes remain owned by the configured global Resource store. Existing Execution/Task finalization paths reuse that History boundary and retain their existing outcomes/no-replay behavior.

Use standard JSON serialization/decoding in `HistoryStore` and `HistoryReader`; `payload_json` already supports null. Keep the existing lexical projection: null contributes no invented search term, while the change type, parameter name, final path, present inline strings, and stored omission metadata remain searchable context. No extra Action Change embedding or Resource-body expansion is introduced. Common Output retains ownership of whole-response limiting and any ordinary whole-result Resource fallback; null itself has no compatibility/fallback conversion. Workspace search state is unrelated to this change.

### 4. Publish the approved nullable-side extension directly

`command-history` owns the exact public JSON contract; `history` owns capture, compaction, raw-side validity, and size/Resource behavior. Consumers previously assuming only string/Resource sides may now receive null and must interpret it as absence. Both side keys remain present. Preserve all baseline scenarios inside each MODIFIED replacement. The existing plain-text Resource example is qualified by normal classification so it does not imply overriding the already-tested JSON classifier.

## Risks / Trade-offs

- [Empty string or literal null text confused with absence] → Use snapshot membership/string-or-null comparison and explicit empty-value regressions on both node cohorts and directions.
- [Union comparison treated as created-node initialization] → Test against the earliest captured post-creation snapshot and assert no initial-parameter-only diffs.
- [Host validation still rejects valid additions/removals, or accepts malformed raw objects] → Cover both side orientations, required keys, both-null rejection, and unsupported types independently of recorder tests.
- [Nullable public sides affect consumers] → Document the approved direct contract extension; provide no compatibility mode or absence-specific fallback.

## Migration Plan

The approved compactor/null implementation is complete. Existing rows remain readable through their existing JSON decoding; new rows store null using the same SQL schema and version. No SQL migration is required. This completion applies only to membership changes delivered to the recorder; native spare/multiparm event delivery is unverified and deferred (see Residual Event-Coverage Limitation).

## Verification Record

Implemented targets are `src/houbridge/houdini/scripts/history/action_recorder.py` and `src/houbridge/history/changes.py`; the focused tests use fake Houdini/embedding fixtures and installed test dependencies. Parent test, validation, and archive evidence is recorded in `tasks.md`.

| Boundary | Verified evidence |
| --- | --- |
| Recorder | Eight cases: existing/created × add/remove × empty/non-empty raw string. Exercise `ParmTupleChanged(parm_tuple=None)` and assert exact side values, node id, and final path. Cover return-to-baseline, changed-value re-add, created initial parameters, deletion/transience, and ordinary value edits. |
| Host materialization | Accept a single null on either side; retain both keys and genuine empty strings. Reject each missing side key, both-null, extra keys, and non-string/non-null raw values, including omission objects. Verify raw expression strings remain unevaluated. |
| Resource boundary | Both directions with null opposite strings at exactly 4096 and above 4096 UTF-8 bytes, including multibyte values. Retain exact bytes, normal classification (plain text and JSON), omission shape, and token metadata; null/empty sides create no Resource. |
| Store/read/public | Commit materialized additions/removals and read through `HistoryReader`/`HistoryReadService.get`; assert JSON null and empty strings survive with the six exact parameter-change keys and the existing omission object. |
| Search | Null-bearing changes remain projectable and discoverable by parameter name/final path; only present inline values and bounded omission metadata contribute value text. Existing dense-source/RRF behavior remains covered. |

The external reproduction is before-change evidence, not a post-fix green suite: it first asserts the old omission, and two controls assert the old rejection of single-null raw sides. The completed regressions use its observed snapshots and the approved contract; missing-key rejection and ordinary empty-string edits remain controls. Parent-owned tests, strict validation, and diff check passed as recorded in `tasks.md`. Native Houdini event delivery was not tested.

The approved compactor/null scope has been implemented and verified. Native Houdini event delivery was not tested; preserve the explicit residual event-coverage limitation when reusing this design. This does not establish capture of every native spare-parameter or multiparm membership change.
