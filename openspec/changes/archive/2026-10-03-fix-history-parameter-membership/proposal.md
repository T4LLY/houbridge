## Why

Approved HB-02 addresses silently omitted parameter additions/removals: the recorder compares only names present in both snapshots, so net membership changes disappear for existing and newly created nodes. At base `70839fc`, the parent's reproduction demonstrated eight failing membership cases and six passing baseline controls; the user explicitly approved `null による不在表現を許可`.

## What Changes

- Compare the union of parameter names in the existing-node start/final or created-node earliest-post-creation/final snapshots, retaining only net differences.
- **BREAKING**: Extend `parm_changed.before` and `parm_changed.after` to allow JSON `null` exclusively for parameter absence on that side. Both keys remain required; present empty strings remain strings, and both-null records are invalid. Clients may receive null without a compatibility mode or substitute value.
- Accept only strings or null at the raw recorder boundary; retain the existing Resource omission object for oversized present strings after host materialization.
- Preserve created-node initialization suppression, return-to-baseline compaction, deletion/transient-node suppression, and session-id/final-path semantics.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `history`: Define membership-aware net parameter comparison and absence-aware raw-value validation/materialization.
- `command-history`: Extend the complete entry's parameter-change sides to include explicit absence while preserving both keys and Resource omission objects.

## Impact

The approved implementation is complete in the Houdini-injected recorder at `src/houbridge/houdini/scripts/history/action_recorder.py` and host validation/materialization at `src/houbridge/history/changes.py`, with focused recorder, value-contract, persistence/read, and search regressions. Existing JSON storage represents null without a SQL migration or new dependency. Parent verification and strict validation passed. Native Houdini event delivery remains unverified; this change does not claim full spare-parameter or multiparm membership capture, and event-subscription expansion is deferred follow-up work.
