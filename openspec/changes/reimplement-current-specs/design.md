# Design

## 1. Design Goal

Rebuild Houbridge so the implementation follows the current `openspec/specs/` contracts directly rather than preserving the ownership boundaries of the legacy implementation.

The current OpenSpec is normative. This design controls implementation structure and sequencing only; it does not add behavior that is absent from the specs.

## 2. Ownership Boundaries

The implementation is divided into independently owned feature subsystems:

- Session owns the Session registry, live-target selection, new-process launch, promotion, and stale registry cleanup.
- Resource owns global canonical payload persistence, classification metadata, semantic aliases, ordinal state, inspection, retention, and dump behavior.
- Output owns final public serialization limits and whole-result Resource fallback.
- Execution owns synchronous caller-Python invocation state and dispatch orchestration.
- Task owns asynchronous queue/runtime state, frozen dispatch context, output chunks, runtime ownership, recovery, and terminalization.
- History owns only process-incarnation-scoped Session Action History and History recall/search state.
- Search owns workspace Script Search plus transient live Python/VEX/node search feature layers over shared Search primitives.
- Capture owns viewport/window/OCR/turntable production and Capture-specific artifact retention.

Shared infrastructure may be used by those features but must not become a hidden owner of feature persistence.

## 3. State Boundaries

State is separated by lifetime and owner:

- Global operational state: Session registry, `tasks.db`, `resources.db`, and process-incarnation History databases below configured `data_dir`.
- Workspace-derived state: `<cwd>/.houbridge/python` and `<cwd>/.houbridge/search.db`.
- Per-user coordination state: exact-Houdini-process managed-execution locks in a platform-standard user directory independent of `data_dir`.
- Invocation/recovery state: private Temporary Workspace files used only while Execution/Task transport or recovery still requires them.
- Caller-visible temporary results: Temporary Artifact publication below the operating-system temp directory.
- Live Houdini state: current scene, nodes, session-local node ids, and transient live-search capture/index state.

These scopes must not be collapsed into one project runtime or one project database.

## 4. Dependency Direction

Expected dependency direction:

- CLI → feature services.
- Feature services → shared primitives.
- Execution/Task → exact-process coordination and Temporary Workspace.
- Execution/Task → History service boundary when History is enabled.
- Task → Resource service for terminal output Resource creation.
- Resource → classifier / SQLite / Temporary Artifact.
- Output → Resource service only for whole-result fallback.
- Script Search / History Search → shared Search primitives without sharing persistent feature state.
- Capture → Houdini transport / Temporary Artifact / Capture encoders.

Disallowed reverse ownership includes Resource depending on Task/Execution/History, History depending on Task runtime ownership, Transport depending on feature persistence, and workspace Script Search depending on Execution/History persistence.

## 5. Houdini-Injected Code Boundary

Reusable Houdini-side source is kept physically separate from host orchestration under feature-specific `houbridge/houdini/scripts/` modules. Host feature services may compose and dispatch those scripts but must not duplicate their reusable source bodies inline.

Injected code remains minimal to the requested operation. It must not reintroduce legacy snapshot, recipe, persistent identity, or HIP database synchronization responsibilities.

## 6. Persistence Strategy

SQLite databases are database-complete for their owning feature and created only when the requested command needs them.

- `resources.db`: canonical Resource payload and Resource-owned metadata/state only.
- `tasks.db`: Task runtime/queue/output/claim/ordinal state only.
- `history/<session-key>/history.db`: finalized current-process Action History and History search state only.
- `.houbridge/search.db`: rebuildable file-level Script Search derived state only.

HIP Data Blocks and persistent Houdini node userData are not persistence mechanisms for the current architecture.

## 7. Execution and Task Coordination

Synchronous Execution and Async Task share one exact-process serialization primitive keyed by PID plus process-incarnation identity. Task global concurrency remains a separate Task-owned policy.

Task submission freezes the execution inputs required to reproduce the submitted invocation. Runtime recovery distinguishes never-started, possibly-started, and completed executions using Task-owned state and Temporary Workspace markers. A possibly-started caller script is never automatically replayed.

## 8. History Strategy

Session Action History is implemented as a new minimal subsystem rather than a reduced form of the legacy graph-history implementation.

It records only executions that actually start in Houdini, uses session-local node identity inside one process-incarnation database, persists only the six specified Action Change forms, stores net Before/After state, and reuses source embeddings without persisting source bodies.

History preflight failure before Python start is fail-closed. History finalization failure after Python start must not cause Python replay.

## 9. Search Strategy

Low-level embedding, dense similarity, lexical search, RRF/hybrid ranking, filtering, cache, and score formatting are reusable primitives.

Persistent feature state remains separate:

- Script Search indexes one authoritative Python file per semantic document in workspace `search.db`.
- History Search uses the current process-incarnation History database.
- Live Python/VEX/node Search builds transient state from current Houdini state and does not persist that index.

## 10. Output and Temporary Result Strategy

Feature services first construct their complete logical result. The common Output subsystem then decides whether the result is emitted inline or stored as a global Resource fallback, and enforces final serialized hard limits.

Resource inspection commands keep their own explicitly bounded inspection semantics rather than recursively falling back through Output.

Temporary Workspace and Temporary Artifact remain separate: the former is private operational state; the latter is an atomically published caller-visible result.

## 11. Verification Strategy

Implementation proceeds in small, independently verifiable tasks tracked in `tasks.md`.

A task is checked only when its implementation and corresponding automated or explicit integration verification are complete at the checked-out revision. Commit/phase labels are not completion evidence by themselves.

Final acceptance requires:

- Complete Requirement/Scenario traceability.
- Full unit/integration suite success.
- Fresh database schema inspection.
- Import-direction inspection.
- Static legacy-concept audit.
- Public CLI/JSON contract audit.
- Real-Houdini end-to-end integration.
- HIP non-persistence verification.
- Global-state/workspace-state separation verification.

Any contradiction discovered between current OpenSpec requirements is a specification issue, not something to hide in implementation compatibility code.
