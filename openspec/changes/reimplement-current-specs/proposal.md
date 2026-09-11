# Reimplement Houbridge Against Current OpenSpec

## Why

The current `openspec/specs/` tree already defines the intended Houbridge behavior and architectural invariants, but the implementation is being rebuilt from an older codebase whose History, persistence, identity, Search, and execution boundaries differ substantially from the current specification set.

The reimplementation therefore needs one tracked OpenSpec change whose implementation checklist can be advanced as Git history is reconstructed. This change does not introduce a new behavior contract; it brings implementation into conformance with the existing current specifications.

## What Changes

- Rebuild the Houbridge implementation around the current feature ownership boundaries: Resource, Output, Session, Capture, Search, Execution, Task, and Session Action History.
- Separate shared infrastructure for configuration, Houdini transport, exact-process coordination, temporary workspace management, temporary artifact publication, formatting, SQLite access, semantic identity, and low-level Search primitives.
- Implement only the public commands, persistence locations, JSON contracts, and Houdini-facing behavior already defined by the current OpenSpec.
- Remove or avoid legacy Graph History, snapshot, graph diff, recipe, checkpoint/undo/recovery, HIP-embedded database, persistent Houbridge UUID, execution-usage, fragment Script Search, and removed compatibility surfaces where the current OpenSpec excludes them.
- Add tests and final integration gates sufficient to demonstrate conformance to every current Requirement and Scenario.

## Specification Impact

No specification delta is created by this change. `openspec/specs/` is already the normative target contract for the reimplementation, so this change declares `skip_specs: true`.

If implementation work reveals that the desired behavior itself must change, this change must stop using `skip_specs: true` for that behavior change and the affected capability must receive an explicit spec delta before implementation continues.

## Scope

In scope:

- Host-side Python CLI and feature services.
- Reusable Houdini-injected scripts.
- External SQLite and filesystem state defined by current OpenSpec.
- CLI, unit, integration, and real-Houdini verification required by current OpenSpec.
- Removal of legacy implementation dependencies that contradict current OpenSpec.

Out of scope:

- New public capabilities not present in current OpenSpec.
- Compatibility behavior justified only by the previous implementation.
- Migration of legacy HIP-embedded History state or persistent node identity into the new architecture.
- Changes to the current behavior contract without a separate explicit spec delta.
