# Changelog

All notable changes to Houbridge are documented in this file.

This changelog was reconstructed from the repository history and release tags. The 0.3.x entries below correspond to the tagged releases `v0.3.0` through `v0.3.20`.

## [Unreleased]

### Documentation

- Clarify that the 0.3.x line remains pre-beta and intended for personal use; 0.4.0 is planned as the first beta line.
- Document that headless camera capture is currently not supported because of a reproducible Houdini 22.0.x Vulkan Flipbook crash that has been reported to SideFX.

## [0.3.20] - 2026-10-05

### Added

- Added headless camera capture support using the headless Houdini session path.

## [0.3.19] - 2026-10-05

### Added

- Added discard mode to `session stop` for terminating a managed session without preserving scene changes.

## [0.3.18] - 2026-10-05

### Added

- Added graceful `session stop` support.

## [0.3.17] - 2026-10-05

### Added

- Added `session detach` for removing a managed session from Houbridge without terminating Houdini.

## [0.3.16] - 2026-10-05

### Fixed

- Clean stale registered sessions whose Houdini ports have already closed.

## [0.3.15] - 2026-10-05

### Fixed

- Use `hbatch` for the headless session lifecycle.

## [0.3.14] - 2026-10-04

### Fixed

- Correct native capture HDK includes.

## [0.3.13] - 2026-10-04

### Fixed

- Use opaque black backgrounds for analysis captures.

## [0.3.12] - 2026-10-04

### Fixed

- Match camera analysis output correctly at very small resolutions.

## [0.3.11] - 2026-10-04

### Fixed

- Reuse already-loaded native capture DSOs instead of reloading them unnecessarily.

## [0.3.10] - 2026-10-04

### Fixed

- Include transparent geometry in depth and grid analysis passes.

## [0.3.9] - 2026-10-04

### Fixed

- Support UV analysis scene hooks.

## [0.3.8] - 2026-10-04

### Added

- Added curvature capture analysis.

## [0.3.7] - 2026-10-04

### Added

- Added object-ID capture analysis.

## [0.3.6] - 2026-10-04

### Added

- Added the shared displayed-geometry normal capture pass.

## [0.3.5] - 2026-10-04

### Added

- Added camera depth and grid analysis passes.

## [0.3.4] - 2026-10-04

### Added

- Added viewport depth and grid analysis passes.

## [0.3.3] - 2026-10-04

### Added

- Added a shared capture-analysis boundary used by viewport and camera analysis paths.

## [0.3.2] - 2026-10-04

### Added

- Added the native capture infrastructure used by the analysis-pass implementation.

### Fixed

- Preserve history parameter membership changes, including spare parameter template changes.
- Prefilter singleton search membership and avoid unnecessary history-change hydration.
- Isolate task failures before dispatch and revalidate synchronous and asynchronous targets at the dispatch boundary.
- Preserve completed task handoff acknowledgement and task-runtime failures.
- Start task timeouts at the dispatch boundary and retain task invocation ownership until workspace cleanup completes.
- Release history callbacks after wrapper failures and bound capture-sequence lock waits.
- Roll back partially-created capture visualizers after capture setup failures.
- Expire resources atomically on writes and contain task lock acquisition errors.
- Reduce JSON search work by sweeping spans first and enriching only returned hits.
- Keep internal script filenames out of public task arguments.

### Documentation

- Defined the script staging workflow.
- Specified the capture analysis-pass design and synchronized the affected OpenSpec contracts.
- Recorded independent review findings and their dispositions.

## [0.3.1] - 2026-10-02

### Added

- Added `hip info` and `hip save` commands.
- Added wrapper-file execution support.
- Made the live-node capture wrapper exportable.
- Excluded underscore-prefixed scripts from default script search.

## [0.3.0] - 2026-10-02

### Added

- Established the core CLI, configuration layering, state ownership paths, SQLite boundaries, temporary workspace handling, and Houdini transport boundary.
- Added session registry management, session creation, promotion, stale cleanup, and attachment to existing Houdini sessions.
- Added synchronous Python execution and asynchronous task submission, scheduling, recovery, streaming, and completion handoff.
- Added global resource storage, classification, semantic identity, retention, inspection, and temporary dump support.
- Added workspace script search, live-code search, live-node search, and shared hybrid ranking primitives.
- Added viewport, window, turntable, and camera capture workflows, including Scene Viewer pane discovery and pane selection.
- Added session action history, execution history, task history, history search, and recall.
- Added AI skills for the Houdini CLI bridge and Houdini script authoring.
- Added full transport output mode and the hidden exec-code wrapper path.

### Changed

- Replaced direct port-selection semantics with the session registry model.
- Unified hybrid search ranking.
- Shared Scene Viewer lifecycle and capture-pane discovery across capture commands.
- Changed window capture to use screen pixels.
- Removed the embedded capture OCR command and implementation before the 0.3.x line was finalized.

### Fixed

- Hardened session registry mutation, stale-session handling, process-incarnation validation, bootstrap diagnostics, and primary-session promotion.
- Bounded session/history coordination, SQLite writer contention, and history retirement waits.
- Improved task failure finalization and task-stream recovery behavior.
- Preserved monotonic capture sequences after output removal and cleaned stale temporary publish staging files.
- Added standard macOS Houdini installation discovery and older-SQLite search compatibility.

### Documentation

- Added the initial README, installation and usage guidance, public CLI parameter documentation, and MIT license.
- Refined the OpenSpec contracts for commands, outputs, sessions, resources, search, history, and storage boundaries during the initial implementation cycle.
