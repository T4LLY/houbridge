# Tasks

> This checklist implements the existing current OpenSpec; this change intentionally has no spec delta.
> Mark a task `[x]` only when the implementation and its verification are complete at the checked-out revision.
> Git commit or external Phase labels are reconstruction aids, not completion evidence.
> If current OpenSpec and implementation disagree, leave the affected task unchecked and resolve the specification contradiction explicitly.

## 1. CLI foundation and public contract

- [x] 1.1 Install exactly one `houbridge` root console entry point and keep the public top-level command groups explicit.
- [x] 1.2 Implement one compact public JSON serializer used by dispatched command results.
- [x] 1.3 Implement the common `BridgeError` JSON envelope and route expected command failures through it.
- [x] 1.4 Wrap unexpected internal failures into the shared internal-error envelope without converting CLI usage errors.
- [x] 1.5 Preserve Typer/framework usage errors as CLI text rather than dispatched JSON failures.
- [ ] 1.6 Implement shared registered-session selection for every Houdini-facing command.
- [x] 1.7 Implement the shared public date-time formatter.
- [ ] 1.8 Implement canonical public numeric lexical formatting, including fixed Search score formatting.
- [ ] 1.9 Route completed logical command payloads through one common `emit_result`/Output boundary.
- [ ] 1.10 Enforce the final hard serialized-JSON boundary after payload construction and Output fallback.
- [ ] 1.11 Keep feature command modules free of private output-limit/fallback implementations.
- [ ] 1.12 Add regression tests for root command installation, command surface, JSON/error envelopes, usage errors, session selection, and shared formatting.

## 2. Configuration and state-path resolution

- [x] 2.1 Define generated defaults for storage, Houdini launch/transport, Resource inspection, Task concurrency, History enablement, screenshot limits/retention, Search, and Output.
- [x] 2.2 Load global configuration and optionally merge the current directory `.houbridge.toml` override.
- [x] 2.3 Allow local overrides only for settings explicitly permitted by OpenSpec.
- [x] 2.4 Reject local overrides of global-only operational settings instead of silently ignoring them.
- [x] 2.5 Resolve `[storage].data_dir` as the single global operational data directory.
- [x] 2.6 Keep bridge-port selection out of persistent configuration and Houdini-facing invocation options.
- [x] 2.7 Resolve Houdini launch/transport timeout and executable settings independently from Session registry state.
- [x] 2.8 Resolve workspace Script Search enablement and workspace-local persistence settings.
- [x] 2.9 Resolve embedding profile and hybrid-ranking settings for Search.
- [x] 2.10 Resolve bounded Resource inspection settings and reject values above fixed hard limits.
- [x] 2.11 Resolve `[task].max_concurrency` as Async-Task-only concurrency with generated default `1`.
- [x] 2.12 Resolve effective `[history].enabled` with generated default `true`.
- [x] 2.13 Resolve screenshot size limits and Capture retention independently from Resource TTL.
- [x] 2.14 Resolve the shared `[output].inline_max_tokens` threshold and reject configuration above absolute Output limits.
- [x] 2.15 Cache unchanged TOML parsing while detecting actual config file changes.
- [x] 2.16 Implement `GlobalDataPaths` for shared Session/Task/Resource/History operational state.
- [x] 2.17 Implement `WorkspaceSearchPaths` for `<cwd>/.houbridge/python` and `<cwd>/.houbridge/search.db` only.
- [x] 2.18 Add configuration and path-resolution tests covering global/local precedence, invalid local overrides, defaults, hard limits, and cwd separation.

## 3. Houdini transport and exact-process coordination

- [x] 3.1 Resolve SideFX/Houdini installations and derive a subprocess environment sufficient for SideFX command-line tools.
- [x] 3.2 Implement local serverless transport through Houdini openport and SideFX `hcommand` without adding an HTTP/RPC/MCP daemon.
- [ ] 3.3 Keep reusable injected Houdini source under feature-specific `houbridge/houdini/scripts/` modules instead of embedding full reusable bodies in host orchestration.
- [x] 3.4 Probe and represent Houdini process identity as PID plus process-start/incarnation identity.
- [x] 3.5 Place managed-execution coordination locks in a fixed platform-standard per-user Houbridge directory independent of `[storage].data_dir`.
- [x] 3.6 Implement one exact-process managed-execution lock shared by synchronous Exec and Async Task.
- [x] 3.7 Surface SideFX transport establishment/execution failures without fabricating Python success.
- [x] 3.8 Add transport, installation-resolution, process-identity, and shared-lock tests.

## 4. Session runtime and CLI

- [x] 4.1 Define the global `sessions.json` registry representation, including registry-level primary selection and registered Session records.
- [x] 4.2 Validate registered Sessions using live PID/process-incarnation information and a probe of the recorded port.
- [x] 4.3 Resolve a target from explicit `--session` or the registry primary without silently selecting another Session.
- [x] 4.4 Implement generic Session inspection and expose only the OpenSpec public Session fields.
- [x] 4.5 Resolve `session new` launch executable precedence as invocation `--hcommand` → global `[houdini].hcommand` → default `houdini`.
- [x] 4.6 Make `session new` always create a new Houdini process rather than probing for a reusable process.
- [x] 4.7 Bootstrap the launched process with Houdini `openport -a` and record Houdini's selected port.
- [x] 4.8 Validate `session new --file` before launch and load that HIP only into the newly created process.
- [x] 4.9 Support the specified GUI/headless process modes without choosing a license edition.
- [x] 4.10 Bound startup polling with configured timeout/interval and terminate failed launches that never establish a usable bridge port.
- [x] 4.11 On Windows, isolate an intentionally launched Houdini GUI process from unrelated later console Ctrl+C handling.
- [x] 4.12 Implement stale Session cleanup without automatically promoting another Session when the primary disappears.
- [x] 4.13 Implement explicit `session promote` and require the target Session to be registered and live.
- [x] 4.14 Keep Session bootstrap/probe injected helpers under `houbridge/houdini/scripts/session/`.
- [x] 4.15 Wire `session info`, `session new`, and `session promote` to the Session services and shared error/output boundaries.
- [x] 4.16 Add Session registry, info, new, stale-cleanup, promotion, bootstrap, and CLI tests.

## 5. Temporary Workspace and Temporary Artifact boundaries

- [x] 5.1 Allocate collision-safe private Temporary Workspaces below the operating-system temporary root for managed Execution/Task invocations.
- [x] 5.2 Publish started markers atomically only after invocation state proves caller Python may have started.
- [x] 5.3 Publish completion markers atomically only after Python outcome and stream flush are established.
- [x] 5.4 Retain active/recoverable Temporary Workspaces only while Task recovery or terminal finalization may need them.
- [x] 5.5 Delete finished private workspaces after authoritative Task/Resource state no longer depends on them.
- [x] 5.6 Implement one shared Temporary Artifact namespace below the operating-system temporary directory.
- [x] 5.7 Reserve collision-safe final artifact paths and publish exact completed bytes/files atomically.
- [x] 5.8 Keep MIME/extension classification in the producing feature rather than in Temporary Artifact.
- [x] 5.9 Expose shared cleanup mechanics while leaving retention duration and cleanup trigger owned by the producing feature.
- [x] 5.10 Keep private Temporary Workspace files completely separate from caller-visible Temporary Artifacts.
- [x] 5.11 Add temporary-boundary tests for atomic publication, collision safety, exact bytes, cleanup scope, and Workspace/Artifact separation.

## 6. Resource persistence and inspection

- [x] 6.1 Create global `<data-dir>/resources.db` schema that is database-complete for payload bytes, canonical identity, content metadata, semantic alias/tag state, ordinal state, and retention state.
- [x] 6.2 Store exact Resource payload bytes in SQLite and make Resource lookup independent of cwd.
- [x] 6.3 Implement one shared payload classifier using magic detection, strict UTF-8/control-character handling, and JSON parsing in the specified order.
- [x] 6.4 Use lowercase SHA-256 of exact payload bytes as canonical Resource identity and deduplicate identical payloads.
- [x] 6.5 Implement shared feature-agnostic semantic-base generation with caller-owned fallback stems.
- [x] 6.6 Generate Resource aliases from three usable Potion tags and deterministic semantic text derived from classified Resource content.
- [x] 6.7 Filter unusable semantic tag atoms and keep semantic ordinal allocation independent from retained Resource rows.
- [x] 6.8 Commit payload upsert, classification metadata, alias allocation, ordinal reservation, and retention refresh in one SQLite transaction.
- [x] 6.9 Prevent alias/ordinal duplication under concurrent writers and prevent cleanup/write races from deleting freshly refreshed payloads.
- [x] 6.10 Implement 72-hour active Resource retention with refresh on write/rewrite and no retention extension on reads.
- [x] 6.11 Keep generic Resource metadata minimal and free of Task, Execution, History, target, or dispatch-specific fields.
- [x] 6.12 Allow Execution/Task output payloads to be stored as Resources without changing generic Resource metadata.
- [x] 6.13 Implement bounded Resource metadata inspection and full-get behavior using final serialized size limits.
- [x] 6.14 Implement UTF-8-safe bounded slicing with explicit offset/limit validation.
- [x] 6.15 Implement bounded literal text search and structural JSON context for JSON matches.
- [x] 6.16 Reject invalid inspection/search/slice operations with shared Resource errors.
- [x] 6.17 Implement Resource dump as exact stored bytes published through Temporary Artifact with feature-selected extension and fallback `.bin`.
- [x] 6.18 Wire `resource info`, `dump`, `get`, `slice`, and `search` to the configured global Resource store.
- [x] 6.19 Keep Resource inspection operations out of recursive whole-result Resource fallback.
- [x] 6.20 Add Resource schema, classifier, identity, semantic-id, transaction/concurrency, retention, reader, dump, and CLI tests.

## 7. Common Output Policy

- [x] 7.1 Implement one shared token estimator/inline threshold used by public command payloads.
- [x] 7.2 Implement whole-result Resource fallback for oversized logical command results.
- [x] 7.3 Store Output fallback Resources in the configured global Resource store and return only the bounded fallback envelope.
- [x] 7.4 Enforce fixed absolute token/serialized-byte limits even after fallback/serialization.
- [x] 7.5 Keep Resource inspection bounded by its own requested inspection semantics rather than recursively applying generic fallback.
- [ ] 7.6 Remove feature-specific token thresholds, truncation rules, cursor workarounds, and duplicate Output Policy implementations.
- [x] 7.7 Add Output tests covering inline success, Resource fallback, hard boundaries, canonical JSON serialization, and Search/OCR/Task fallback reuse.

## 8. Synchronous Execution

- [x] 8.1 Read caller Python with Python source-encoding semantics, normalize the absolute file path, and reject real NUL characters before Houdini dispatch.
- [x] 8.2 Model one synchronous invocation with file, argv, purpose, cwd, selected Session, and exact source/hash as invocation-local state.
- [x] 8.3 Build injected execution source under `houbridge/houdini/scripts/execution/` and preserve the defined execution namespace.
- [x] 8.4 Save/replace/restore Houdini-side `sys.argv` around caller execution while preserving `--` script argument order and duplicates.
- [x] 8.5 Capture stdout, stderr, declared result, and Python exception/traceback without mixing them into transport noise.
- [x] 8.6 Classify declared synchronous results deterministically as public JSON or bounded representation according to the execution contract.
- [x] 8.7 Use a private Temporary Workspace for execution transport files and markers.
- [x] 8.8 Resolve and probe the selected registered Houdini Session before dispatch.
- [x] 8.9 Acquire the exact-process managed-execution lock around caller Python dispatch.
- [ ] 8.10 Expose a History preflight/finalization boundary without letting Execution directly own History tables.
- [x] 8.11 Materialize required execution artifacts as Resources and pass the logical synchronous result through the common Output Policy.
- [x] 8.12 Implement public `exec --file PATH [--purpose TEXT] [--async] [--session N] [-- SCRIPT_ARGS...]` parsing with no `--code` source path.
- [x] 8.13 Keep Async operational persistence out of Execution and hand asynchronous submission to Task.
- [x] 8.14 Separate finite dispatch-establishment timeout from unbounded caller-Python run duration.
- [x] 8.15 Add Execution source, injected-runtime, presentation, service, CLI, transport-failure, locking, argv, and result-classification tests.

## 9. Async Task subsystem

- [x] 9.1 Create one global `<data-dir>/tasks.db` schema for Task rows, output chunks, semantic ordinal state, runtime ownership, and claims.
- [x] 9.2 Expose exactly the four public states `queued`, `running`, `completed`, and `failed` with correct transition timing.
- [x] 9.3 Read and freeze exact submitted Python source before Task creation and retain it only while queued/running/recoverable.
- [x] 9.4 Generate Task semantic IDs from submitted source only, using caller fallback `task-unknown` and ordinal state independent of retained Task rows.
- [ ] 9.5 Freeze absolute file, args, purpose, origin cwd, Session, target port, PID/process-incarnation, transport context, History decision, and requested embedding profile at submission.
- [x] 9.6 Implement recoverable on-demand Task Runtime ownership/activation in `tasks.db` rather than a permanent daemon flag.
- [x] 9.7 Implement queue claiming/scheduling with global `[task].max_concurrency` enforcement.
- [x] 9.8 Revalidate the exact bound Houdini process incarnation immediately before dispatch and fail instead of retargeting a replacement process.
- [x] 9.9 Acquire the same exact-process managed-execution lock used by synchronous Exec.
- [x] 9.10 Persist stdout/stderr incrementally as ordered Task-owned chunks in `tasks.db`.
- [x] 9.11 Reconstruct accumulated stdout/stderr as logical Task state without exposing chunk ids/cursors.
- [x] 9.12 Represent Python exceptions as Task failure with traceback in stderr while representing Task Runtime failures as structured runtime errors.
- [x] 9.13 Use atomic started/completion markers plus runtime claims to distinguish never-started, possibly-started, and completed invocations.
- [x] 9.14 Recover/finalize a possibly-started Task without automatically replaying caller Python.
- [ ] 9.15 Preserve frozen History context through queue wait and hand it to the shared History boundary only if caller Python actually starts.
- [x] 9.16 Create one successful completion JSON Resource containing exactly Task-defined stdout/stderr payload.
- [x] 9.17 Clear source bodies at terminalization and retain terminal Tasks for the effective Resource TTL without expiring active Tasks.
- [x] 9.18 Make Task reset atomic with active-state checks and reset semantic ordinals only on successful reset.
- [x] 9.19 Implement stable newest-first `task list` ordering and the specified `task get` fields/omission rules.
- [x] 9.20 Trigger lazy runtime recovery/activation from successful `exec --async` submission and every public Task command.
- [x] 9.21 Wire `task get`, `task list`, and `task reset` to the global Task store and shared error/output boundaries.
- [x] 9.22 Add Task persistence, semantic-id, target-binding, concurrency, scheduler-race, streaming, crash-recovery, no-replay, completion, TTL/reset, CLI, and async-handoff tests.

## 10. Shared Search primitives

- [x] 10.1 Implement embedding provider/profile handling with profile identity kept separable across indexes.
- [x] 10.2 Implement dense cosine-similarity primitives without feature ownership.
- [x] 10.3 Implement lexical FTS/BM25 primitives without feature ownership.
- [x] 10.4 Implement RRF/hybrid candidate fusion using configured ranking parameters.
- [x] 10.5 Implement reusable SQLite vector/filter/cache helpers without coupling them to Script Search or History.
- [x] 10.6 Route every public Search score through the shared canonical score formatter.
- [x] 10.7 Add Search-primitive tests for dense, lexical, hybrid/RRF, profile separation, cache/filter behavior, and public score formatting.

## 11. Workspace Script Search

- [x] 11.1 Resolve Script Search exclusively from `<cwd>/.houbridge/python` and `<cwd>/.houbridge/search.db`.
- [x] 11.2 Treat Python files as authoritative source and `search.db` only as rebuildable derived index/cache state.
- [x] 11.3 Index exactly one semantic retrieval document per Python file rather than function/class fragments.
- [x] 11.4 Extract an optional Python module docstring as the file-level script description without inventing a description when absent.
- [x] 11.5 Read Python files with declared source-encoding support.
- [x] 11.6 Keep syntax-error files searchable without fabricating semantic structure or description metadata.
- [x] 11.7 Reconcile unindexed, changed, and deleted files automatically before returning search results.
- [x] 11.8 Re-index file-level embeddings when the configured embedding profile changes.
- [x] 11.9 Allow workspace Script Search indexing to be disabled as one feature unit.
- [x] 11.10 Return the minimal script-search result envelope with path, score, and description only when present.
- [x] 11.11 Remove execution-usage/count coupling and fragment-search concepts from Script Search.
- [x] 11.12 Wire `search script` to workspace Script Search without requiring Houdini or Session selection.
- [x] 11.13 Add Script Search tests for cwd isolation, file authority, one-file documents, docstrings, encodings, syntax errors, reconciliation, profile changes, disablement, and CLI output.

## 12. Live Houdini Search

- [x] 12.1 Keep reusable live-search capture helpers under `houbridge/houdini/scripts/search/`.
- [x] 12.2 Implement the explicit built-in VEX/Python node-type → source-parameter extractor registry.
- [x] 12.3 Read live code with `parm.rawValue()`, ignore missing/failed/empty sources, and deduplicate overlapping node scopes by session id.
- [x] 12.4 Build live Python/VEX semantic indexes transiently from current Houdini state and never persist them as workspace/session search state.
- [x] 12.5 Support path scoping and mutually exclusive positional query vs `--like NODE_PATH` live-code similarity search.
- [x] 12.6 Store matched live source bodies as Resources and return Resource-backed hits without inline source bodies.
- [x] 12.7 Capture current Houdini node instances for live Node Search without persistent indexing.
- [x] 12.8 Rank Node Search by case-insensitive exact → prefix → substring match class with stable path tie-break and no numeric public score.
- [x] 12.9 Apply common Output fallback to oversized live-code/node result envelopes.
- [x] 12.10 Expose matching `search python`, `search vex`, and `search node` CLI contracts with shared Session selection.
- [x] 12.11 Add live-code/live-node tests for extractor matching, namespaces, raw source, transient indexing, path scope, like-node search, Resource-backed code hits, node ranking, deduplication, CLI syntax, and Output fallback.

## 13. Capture subsystem

- [x] 13.1 Keep reusable Capture-injected helpers under `houbridge/houdini/scripts/capture/` and host orchestration outside that tree.
- [x] 13.2 Inspect visible Scene Viewer viewports and expose only stable public viewport information.
- [x] 13.3 Capture the active viewport to PNG.
- [x] 13.4 Implement directed top/bottom/front/back/left/right/persp/uv captures using cloned/temporary viewer state without modifying the user's viewer.
- [x] 13.5 Implement the fixed captioned four-view quad image.
- [x] 13.6 Parse screenshot preset JSON strictly and reject unknown keys/invalid values.
- [x] 13.7 Enforce viewport/window/turntable-specific preset capability restrictions.
- [x] 13.8 Apply requested positive scale before aspect-preserving clamp to configured maximum dimensions.
- [x] 13.9 Publish Capture outputs through Temporary Artifact with readable collision-safe names, atomic finalization, and Capture-owned lazy retention.
- [x] 13.10 Capture the Houdini main application window through the supported OS/window path.
- [x] 13.11 Transform pane-tab/viewport UI bounds into coordinates relative to the final cropped/scaled image.
- [x] 13.12 Resolve unambiguous supported window crop selectors and reject ambiguous/unsupported crop requests.
- [x] 13.13 Implement OCR detection/recognition result normalization, duplicate-string grouping, scores, and compact bounding boxes.
- [x] 13.14 Keep OCR initialization quiet, use the standard Hugging Face assets cache hierarchy, and use the specified RapidOCR/ONNX tiny PP-OCRv6 profile with classification disabled.
- [x] 13.15 Pass complete OCR logical results to common Output Policy without OCR-specific thresholds.
- [ ] 13.16 Implement clockwise 360-degree turntable orbit from the current Perspective camera with optional positive finite pivot distance.
- [ ] 13.17 Treat turntable PNG frames as private encoding intermediates and remove them after successful/failed finalization as specified.
- [ ] 13.18 Encode turntable output only as MP4 through external ffmpeg and do not expose an `--ffmpeg` public option.
- [ ] 13.19 Wire viewport/info, window, OCR, and turntable CLI contracts with their exact success JSON shapes.
- [ ] 13.20 Add Capture tests for view selection, cloned-view preservation, quad layout, preset validation, scale/clamp, window bounds/crop, temp publication/retention, OCR, turntable orbit/distance/ffmpeg/frame cleanup, and CLI output.

## 14. Session Action History

- [ ] 14.1 Resolve one History database per exact Houdini process incarnation at `<data-dir>/history/<session-key>/history.db`.
- [ ] 14.2 Install process-local HIP lifecycle handling that destroys current History on successful scene load/clear replacement.
- [ ] 14.3 Retire stale History directories when the owning Houdini process incarnation is no longer current.
- [ ] 14.4 Create a database-complete History schema for entries, six Action Changes, source embedding/profile state, and History search state without graph/recipe/checkpoint/Task/output/source-body tables.
- [ ] 14.5 Allocate session-local History ids monotonically.
- [ ] 14.6 Use `hou.Node.sessionId()` only as identity inside the owning process-incarnation History and keep path/type as human-readable context.
- [ ] 14.7 Honor effective `[history].enabled`, default-on, without initializing recorder/embedding/write work when disabled.
- [ ] 14.8 Capture a lightweight invocation-local baseline around caller Python rather than persisting snapshots.
- [ ] 14.9 Record exactly `node_created`, `node_deleted`, `node_renamed`, `parm_changed`, `input_rewired`, and `flag_changed` and compact them to net Before/After changes.
- [ ] 14.10 Store parameter raw unevaluated Before/After values; spill values over the UTF-8 byte threshold to Resource references with token count.
- [ ] 14.11 Persist one minimal terminal History entry only for executions whose caller Python actually started, including failed Python executions when finalization is possible.
- [ ] 14.12 Hash exact executed source, store/reuse embeddings by source-hash/profile, pin one profile per History DB, and never persist source bodies.
- [ ] 14.13 Fail closed on enabled-History preflight before Python starts; after Python starts never replay caller Python solely because History finalization failed.
- [ ] 14.14 Carry the same History finalization boundary through Async Task using frozen submission context.
- [ ] 14.15 Implement History search using source semantic embeddings plus lexical purpose/file/args/Action context without Action Change embeddings.
- [ ] 14.16 Implement History reader/get and chronological newest-first list independently from search ranking.
- [ ] 14.17 Wire `history search`, `history get`, and `history list` to registered live Session selection, shared formatting, Output Policy, and error handling.
- [ ] 14.18 Add History lifecycle, schema, identity, change-compaction, large-parameter spill, sync/async integration, embedding reuse/profile pinning, search/read/list, stale-retirement, and CLI tests.

## 15. Houbridge Skill authoring contract

- [ ] 15.1 Update the actual Houbridge Skill so every newly created `.houbridge/python/*.py` script receives a non-empty valid module docstring describing its purpose.
- [ ] 15.2 Keep that module docstring as the only authoritative description metadata and do not create sidecar JSON/YAML/TOML or custom description-comment metadata.
- [x] 15.3 Do not make module docstrings a runtime prerequisite for existing or user-authored workspace scripts.
- [ ] 15.4 Verify Local Script Search exposes the Skill-created module docstring as `description` while still accepting scripts with no description.
- [ ] 15.5 Add or update Skill-level verification for new-script authoring and compatibility with existing scripts.

## 16. Cross-feature architecture and legacy guards

- [ ] 16.1 Keep composition-root wiring responsible for feature-to-feature service composition and construct only the runtime needed by the selected command.
- [ ] 16.2 Keep top-level Resource, Output, Session, Capture, Search, Execution, Task, and History ownership independent with no prohibited reverse dependencies.
- [ ] 16.3 Keep live Houdini state, workspace-derived Search state, global Task/Resource state, process-incarnation History state, configuration state, and invocation-local temporary state in their specified scopes.
- [ ] 16.4 Keep Resource persistence database-complete/global and keep global data-directory selection independent from cwd.
- [ ] 16.5 Keep Houbridge persistence out of HIP Data Blocks and do not assign persistent Houbridge UUID userData to nodes.
- [ ] 16.6 Keep generic semantic-base generation feature-agnostic while Resource/Task own their own ordinal allocation/fallback stems.
- [ ] 16.7 Keep canonical formatting, Output limiting, Temporary Artifact publication, and exact-process execution coordination centralized shared primitives.
- [ ] 16.8 Guard the public surface against removed `exec --code`, public `--root`, `hip read`, fragment Script Search, `search script --count`, and other removed compatibility entry points.
- [ ] 16.9 Guard source/schema/imports against legacy GraphSnapshot, graph diff, recipe, checkpoint/undo/recovery, embedded History DB, semantic-head/event, execution-usage, and persistent UUID concepts.
- [ ] 16.10 Keep host orchestration physically separate from reusable injected Houdini code for Session, Execution, Task, Search, Capture, and History.
- [ ] 16.11 Add static/regression tests that fail if removed legacy symbols, commands, schemas, persistence paths, or dependency directions reappear.

## 17. Cross-spec acceptance and final audit

- [ ] 17.1 Build a complete current-OpenSpec Requirement traceability matrix with implementation and verification evidence for every Requirement.
- [ ] 17.2 Run the complete unit/integration suite and resolve every failure without adding out-of-spec production compatibility branches.
- [ ] 17.3 Generate fresh `resources.db`, `tasks.db`, process-incarnation `history.db`, and workspace `search.db` and inspect each schema for allowed and forbidden ownership concepts.
- [ ] 17.4 Inspect the import graph and verify CLI → feature services → shared primitives direction with no prohibited reverse feature dependencies.
- [ ] 17.5 Run static searches for all removed legacy concepts and review every remaining hit rather than relying only on zero-match counts.
- [ ] 17.6 Compare the full public command surface, options, success JSON, failure JSON, scalar formatting, and final hard-output behavior against current OpenSpec.
- [ ] 17.7 Run a real-Houdini Session → Exec → Task → History → Resource → Search → Capture integration flow.
- [ ] 17.8 Save a HIP after Houbridge activity and verify no Houbridge persistent DB Data Block or persistent UUID userData is added.
- [ ] 17.9 Change cwd and verify global Session/Task/Resource/History state remains shared while workspace Script Search source/index remain isolated.
- [ ] 17.10 Produce the final audit report and leave the change incomplete if any Requirement, Scenario, missing Skill artifact, or specification contradiction remains unresolved.
