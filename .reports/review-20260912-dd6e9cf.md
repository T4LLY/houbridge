# houbridge2 — Independent Code Review

- **Commit:** `dd6e9cf` (2026-09-12)
- **Scope:** Full read of `src/houbridge` (~8.7k lines): config/paths/errors/formatting/semantic_id, process coordination, temporary workspace/artifacts, db, output, session (registry/launcher/resolver/probe/stale/new/promote/info), history (store/schema/locking/identity/invocation/execution/changes/reader/retirement/search/search_schema, task/history, execution/history), execution (sync runtime/service/source/workspace/script/models/presentation), task (schema/store/runtime_store/runner/runtime/worker/supervisor/streaming/invocation_store/completion/async_submission/activation/control/workspace/submission/target/script/service/models/presentation), resource (store/reader/schema/classifier/dump/models), capture (all), search (dense/embedding/lexical/rrf/sqlite_filter), script_search, live_code_search, live_node_search, houdini (transport/installations + all injected scripts under houdini/scripts), cli (all commands). Test suite executed.
- **Method:** Direct source inspection of every module (no delegation); cross-file tracing of state machines (task lifecycle, runtime ownership/claims, session registry), locking, caching, and error paths; Houdini-side injected scripts reviewed as runtime counterparts; test suite run (`uv run --extra test pytest` → 9 failed / 434 passed) with per-failure root-cause decomposition including config-path environment experiments. No source code modified.
- **Classification:** High-confidence candidates / Plausible candidates / Investigation leads.
- **Model:** `glm-5.3`

---

## Verification notes (checks that rejected suspected issues)

- **Task finalize replay after worker thread crash is safe.** `history/store.py commit_entry` dedups by `execution_key` (`task:{id}`) and `resource/store.py put_bytes` dedups by `canonical_id` sha256 (UPSERT returning same alias). Re-running `_finalize` after a crash re-produces identical state. Not reported as a finding.
- **Capture sequence monotonicity fix** (`capture/sequence.py reserve()` = `max(last_reserved, existing_max_files)+1` under lock) verified correct, including `_publish_sequenced` retry-on-FileExistsError.
- **`houbridge/houbridge` doubled path segment** in config/data paths is stable platformdirs appauthor behavior, not a bug.
- **`houbridge\houbridge` config path env-override experiment**: setting `LOCALAPPDATA`/`APPDATA` does not redirect `default_config_path()` on platformdirs 4.11 (home-derived) — relevant to C4/C18.

---

## High-confidence candidates

### [Fixed] C1. `session info` (no args) fails entirely whenever any registered session has died

- **Severity:** Medium
- **Confidence:** High-confidence candidate
- **Affected:** `src/houbridge/session/info.py` (`SessionInfoService.inspect`, lines ~35–40); `src/houbridge/cli/session_cmd.py` (`info_command`)
- **Description:** `inspect(None)` iterates every registered session and calls `resolve_record`, which raises `session_unreachable` for the first dead/stale session. Unlike `promote` and `new` (which run `cleanup_locked` first), `info_command` performs no stale cleanup, and the listing loop has no per-session error isolation.
- **Why it matters:** The one command users reach for to inspect state becomes unusable exactly when something is wrong (a session exited). A single dead session hides all surviving sessions.
- **Evidence:** `session/info.py:35-40` — `resolve_record(...)` inside the per-session loop with no try/except; `cli/session_cmd.py info_command` calls `inspect` directly; contrast `session/promote.py` / `session/new.py` which call `cleanup_locked` under the registry lock before resolving.
- **Expected impact:** `houbridge session info` returns a `session_unreachable` error and lists nothing; users must guess which session died or run promote to trigger cleanup.
- **Trigger conditions:** Any registered Houdini session process exits (or becomes unreachable) while still present in `sessions.json`, then `session info` is run without `--session`.
- **Suggested verification direction:** Start registry with two fake sessions, kill one PID, run `session info`; expect failure. Fix direction: run `cleanup_locked` (like promote) or skip-and-annotate unreachable sessions in listing mode.

#### Update — 2026-09-12 13:05 — Base dd6e9cf

Verified against the current source. A two-session reproduction with one dead recorded PID caused `SessionInfoService.inspect(None)` to raise `session_unreachable` before the surviving session could be listed. The root cause was that the no-argument info path loaded and resolved the registry directly without the stale cleanup already used by `session new` and `session promote`. The CLI now injects `SessionStaleCleanupService` into `SessionInfoService`; no-argument inspection performs proven-dead cleanup before resolving the remaining sessions, while explicit `--session` behavior is unchanged. Added a regression test covering dead-primary removal with a surviving session and updated the command OpenSpec to define the cleanup boundary.

### [Partially fixed] C2. No post-start timeout or cancellation for running async tasks — hung Houdini Python leaves tasks `running` forever and blocks worker retirement

- **Severity:** High
- **Confidence:** High-confidence candidate (design gap confirmed in source; runtime hang not reproduced)
- **Affected:** `src/houbridge/task/runner.py` (`_monitor` phase-2 `while True` loop); `src/houbridge/houdini/scripts/task/runtime.py` (completion marker writer)
- **Description:** Phase 1 of `_monitor` (dispatch → started marker) has a deadline from `dispatch_started_at + transport_timeout_seconds`. Phase 2 (started → completion marker) loops forever: it drains streams and polls for `completion.json` with no deadline and no cancellation path. The Houdini-side task runtime writes the completion marker only after user Python exits and a best-effort history finalize; failures that occur outside its guarded region (e.g. `_flush_file`/fsync `OSError` on disk-full in the `finally`, or a hang inside history finalize waiting on the history DB file lock) mean the marker is never written while the host keeps waiting.
- **Why it matters:** A single hung task (infinite loop in user Python, blocked fsync, locked history DB inside Houdini) occupies a concurrency slot indefinitely; `retire_runtime_if_idle` never observes zero non-terminal work, so the background worker process never exits; the task can never be cancelled, only manually failed via DB surgery.
- **Evidence:** `task/runner.py` — phase 2 is `while True:` with completion-marker check and stream drains only; no deadline parameter exists for this phase (phase 1 uses `state.dispatch_started_at + transport_timeout_seconds`). `scripts/task/runtime.py` — completion marker written after `finally`-guarded stream flush + history finalize; an `OSError` escaping the guard or a blocking history-finalize skips it. `task/runtime_store.py retire_runtime_if_idle` requires no queued/running tasks and no invocations.
- **Expected impact:** Permanent `running` task; worker process leak; per-target claim (UNIQUE(target_pid, identity)) serializes all subsequent tasks for that Houdini session behind the hung one.
- **Trigger conditions:** Any async task whose user Python never terminates, or whose Houdini-side completion-marker write path raises/hangs after the started marker was written.
- **Suggested verification direction:** Submit a task containing `while True: pass`; observe task stays `running` and worker never retires. Evaluate adding an optional phase-2 deadline (max task wall time) and/or an explicit `task cancel` path that terminates the target script.

#### Update — 2026-09-12 13:12 — Base 4bcb7cb

The finding combines intended behavior with a verified defect. OpenSpec explicitly requires that caller Python may remain `running` indefinitely after the started marker, so no wall-clock timeout or automatic cancellation was added for long-running caller code. The separate post-Python wrapper-failure path was reproduced by forcing `_flush_file` to raise after caller Python returned: `started.json` existed, `completion.json` did not, and the runner previously had no terminal transition while the Houdini target remained live. The wrapper protocol now publishes `python-finished.json` immediately after the Python outcome, best-effort publishes `wrapper-failed.json` for post-Python infrastructure exceptions, and the monitor terminalizes either an observed wrapper-failed marker or an exited hcommand after the Python-finished boundary. Recovery therefore does not replay caller Python. A blocked History-finalize lock remains dependent on C5's unbounded lock wait and is not claimed fixed by this update.

### [ ] C3. Embedding-model download is a hard prerequisite for basic exec/task operation (offline fresh machine cannot run `houbridge exec` or complete async tasks)

- **Severity:** High
- **Confidence:** High-confidence candidate (mechanism fully source-verified; offline behavior of model2vec/HF cache not executed)
- **Affected:** `src/houbridge/history/invocation.py` (`prepare` → `embed_source`); `src/houbridge/semantic_id.py` (PotionSemanticBaseGenerator); `src/houbridge/resource/store.py` (`put_bytes`); `src/houbridge/task/completion.py` (`finalize_success`); `src/houbridge/output/policy.py` (`present` oversized spill); `src/houbridge/history/changes.py` (`_bounded_raw_value` spill); `src/houbridge/search/embedding.py` (Model2VecEmbeddingProvider); `src/houbridge/live_code_search/service.py` (`_present`)
- **Description:** History is enabled by default and `prepare` unconditionally embeds the source (`embed_source`) before execution. On a fresh machine the embedding cache is empty, so `Model2VecEmbeddingProvider` must load `minishlab/potion-code-16M-v2` via `StaticModel.from_pretrained` — a HuggingFace network download on first use. Offline, this raises `embedding_model_load_failed` wrapped as `history_preflight_failed`: the exec never runs. Independently, `ResourceStore.put_bytes` of *new* content requires `PotionSemanticBaseGenerator` (same model family) to derive a semantic base — so async task completion (`finalize_success` → `put_bytes`) fails-and-marks-runtime-failed, oversized sync output spilling to resources fails the whole command despite a known outcome, and parm-value spills/large search hits hit the same wall.
- **Why it matters:** Basic functionality (`exec`, task submission/completion, output-overflow handling) is coupled to ML-model availability and network access. Air-gapped, firewalled, or merely first-use-offline machines experience hard failures or tasks that fail at the finish line.
- **Evidence:** `history/invocation.py prepare` calls `storage.store.embed_source(...)` before staging (no skip-on-unavailable path); `search/embedding.py` — lazy `StaticModel.from_pretrained(profile)` with `BridgeError embedding_model_load_failed`; `semantic_id.py` — no offline fallback, `semantic_id_model_load_failed`; `task/completion.py` — `put_bytes` BridgeError → `mark_runtime_failed(task_resource_finalization_failed)` (task fails *after* Python succeeded); `output/policy.py present` — oversized payload → `put_bytes` whose failure propagates to the CLI result. Config defaults: `[history] enabled = true`, embedding profile `minishlab/potion-code-16M-v2`.
- **Expected impact:** First-use offline: `houbridge exec` errors with `history_preflight_failed`; async tasks complete Python then fail with `task_resource_finalization_failed`; any oversized stdout/stderr/traceback/parm spill fails its command. All resolved only after one successful online model fetch.
- **Trigger conditions:** Fresh install (no HF cache for the profile, empty embedding cache) without network access at first exec/task; or later, any new-content `put_bytes` while the model directory is unavailable/corrupt.
- **Suggested verification direction:** Block network (or point HF_HOME at an empty dir with HF_HUB_OFFLINE=1) on a clean data dir and run `houbridge exec` and an async task; confirm failure codes. Consider lazy/best-effort embedding on prepare, a deterministic fallback semantic base, or graceful degradation for oversized-output spill.

---

## Plausible candidates

### [ ] C4. Config schema evolution hard-fails all commands after upgrade (no migration, no unknown-key tolerance for legacy keys)

- **Severity:** High (UX/reliability)
- **Confidence:** Plausible candidate (observed live on this machine; upgrade path inference)
- **Affected:** `src/houbridge/config.py` (`_validate_schema`); global config `…\houbridge\houbridge\config.toml`
- **Description:** `_validate_schema` rejects unknown top-level keys. The machine's real global config uses an older schema (`storage.root`, `session.port`, `execution.inline_max_tokens`, `history.uuid_user_data_key`, `history.events.*`, `local_script_database.enabled`); the current binary rejects it (`invalid_config: Unsupported config key: storage.root`), and since every CLI command calls `load_config()`, **all** commands fail until the user hand-edits the file. There is no migration, version negotiation, or per-key tolerance.
- **Why it matters:** Any user upgrading across this schema change is fully bricked with an error that doesn't offer a migration path — this exact state was observed on the review machine.
- **Evidence:** Test run: 6 failures across `test_output_policy`, `test_resource_cli` (2), `test_session_cli` (2), `test_task_completion_cli` all traced to `load_config()` parsing the real machine config and rejecting `storage.root`. Config file contents listed during review; `_validate_schema` strict rejection confirmed in source.
- **Expected impact:** Total CLI outage post-upgrade for users with pre-change configs; confusing failure mode remote from the actual change.
- **Trigger conditions:** Upgrade from a version whose default/accepted config contained any key removed/renamed in the current schema.
- **Suggested verification direction:** Add a config containing `storage.root` and run any command. Consider key migration, warn-and-ignore for recognized-legacy keys, or an error message naming the offending key with a suggested fix (it does name the key — add remediation).

### [Fixed] C5. InterprocessFileLock default infinite wait can deadlock CLI/Houdini on a held history DB lock; lifecycle hip-event handler has no timeout at all

- **Severity:** Medium-High
- **Confidence:** Plausible candidate
- **Affected:** `src/houbridge/process_coordination.py` (`InterprocessFileLock.acquire`, `timeout_seconds=None` default, ~lines 84–96); `src/houbridge/history/locking.py` (`history_connection_scope` — no timeout); `src/houbridge/session/registry.py` (`locked()` — no timeout); `src/houbridge/houdini/scripts/history/lifecycle.py` (`_lock` — no timeout, runs on Houdini UI event thread)
- **Description:** Every history-DB connection is wrapped in an interprocess file lock with **infinite** acquire timeout, and the session registry lock likewise. The Houdini-side `lifecycle.py` hip-event callback (AfterLoad/AfterClear) destroys the history DB under the same lock with a no-timeout msvcrt/flock loop — on the Houdini UI thread. If any holder stalls while alive (e.g. a process suspended, a debugger, or a slow operation inside `connection_scope`), every other process blocks forever, and Houdini's UI can freeze entirely.
- **Why it matters:** Infinite blocking turns any stuck holder into a multi-process hang, including a frozen DCC UI — the worst failure mode for a bridge tool. Note the codebase already learned this lesson elsewhere: `ManagedExecutionLock` passes `lock_timeout=120s`.
- **Evidence:** `process_coordination.py:84-96` — `acquire` loops with `timeout_seconds=None` meaning unbounded; `history/locking.py history_connection_scope` and `session/registry.py locked()` pass no timeout; `scripts/history/lifecycle.py _lock` — polling loop without timeout bound invoked from hip event callbacks.
- **Expected impact:** CLI hangs with no diagnostics; Houdini UI freezes on scene load/clear while another process holds the DB lock.
- **Trigger conditions:** History DB (or registry) lock held by a process that stops making progress without dying (suspended, long GC/IO inside the locked section, crash mid-section on POSIX where the fd is held by a surviving child).
- **Suggested verification direction:** Hold the history lock manually (small script) then run `houbridge history …` and load a hip file in Houdini; confirm indefinite block. Add bounded timeouts + `lock_timeout` error code and retry/deferral for the hip-event destroy.

#### Update — 2026-09-12 13:21 — Base 0c89605

Verified the unbounded waits in both `history_connection_scope` and `SessionRegistry.locked`, and reproduced contention with a held History/registry lock. History and Session coordination now use the configured `[houdini].lock_timeout_seconds`; host-side History timeout reports `history_lock_timeout` and Session registry timeout reports `session_registry_lock_timeout`. The Houdini `AfterLoad`/`AfterClear` callback now uses a bounded lock wait. To preserve the scene-reset contract when that wait expires, it publishes a coordination-only pending-reset marker before waiting; the next History connection that acquires the database lock destroys the old DB/WAL/SHM/journal before any read or recreation. Async Task workers receive the same lock timeout when launched. Regression coverage verifies bounded Session/History waits and that a timed-out hip-event reset returns promptly while the pending reset is consumed before the next History connection. The unit suite passed with the existing external `filetype` test stub.

### [Fixed] C6. Sync exec writes the status file after in-Houdini history finalize — a history-DB lock hang converts a successful execution into a transport timeout

- **Severity:** Medium
- **Confidence:** Plausible candidate
- **Affected:** `src/houbridge/houdini/scripts/execution/runtime.py` (status write ordering)
- **Description:** The Houdini-side execution runtime runs user Python, then performs best-effort history finalize (which takes the interprocess history lock), and only afterwards writes the status file atomically. The host-side `transport.execute_script` enforces a timeout on the whole `hcommand` invocation. If history finalize blocks on the lock (see C5), the status file is never written and `hcommand` appears to hang → host raises `transport_timeout` even though the user's Python completed successfully and its stdout was already flushed to the stream files.
- **Why it matters:** Correctly-executed work is reported as transport failure; the caller cannot distinguish "my code hung" from "history bookkeeping hung".
- **Evidence:** `scripts/execution/runtime.py` — ordering: user exec → history finalize (best-effort `except Exception`, but a *blocking* lock is not an exception) → atomic status write; `houdini/transport.py execute_script` — timeout on the synchronous hcommand run; `history/locking.py` — lock has no timeout (C5).
- **Expected impact:** Intermittent false transport failures whenever history finalize stalls past `transport_timeout_seconds`.
- **Trigger conditions:** History enabled; another process holds the per-DB history lock longer than the remaining transport timeout while a sync exec finishes.
- **Suggested verification direction:** Hold history lock, run timed `houbridge exec 'print(1)'`; expect timeout despite completed side effects. Consider writing status before history finalize, or bounding the in-Houdini lock wait.

#### Update — 2026-09-12 13:47 — Base 0c89605

Verified the ordering defect after C5: the synchronous wrapper still published `execution.json` only after in-Houdini History finalization, while the host-side transport timeout covered the entire hcommand call. A caller that had already reached a terminal Python outcome could therefore still be reported as `hcommand_timeout` when only post-Python History bookkeeping consumed the remaining transport budget. The wrapper now atomically publishes the terminal caller status after stdout/stderr/result files are stable and before History finalization. `ExecutionRuntime` preserves that outcome only when History was enabled, `hcommand_timeout` occurs, and the terminal status marker already exists; timeouts before the marker and no-History timeouts still propagate normally. Regression tests verify marker-before-History ordering, preservation of the completed Python outcome in the History-enabled timeout case, and unchanged timeout behavior without History.

### [ ] C7. SQLite connections rely on the default 5s busy timeout under multi-process `BEGIN IMMEDIATE` contention

- **Severity:** Medium
- **Confidence:** Plausible candidate
- **Affected:** `src/houbridge/db/connection.py` (`connect` — no `busy_timeout` PRAGMA); all tasks.db/resources.db/history DB writers (worker poll loops, CLI submissions, retirement, capture cleanups)
- **Description:** `connect()` sets foreign_keys/WAL/synchronous but not `busy_timeout`, leaving Python's default 5000ms. Several hot paths take `BEGIN IMMEDIATE` (task submit, ordinal allocation, `put_bytes`, claim adoption) while a detached worker polls in loops and CLI processes run concurrently. WAL permits concurrent readers, but immediate-write transactions conflict; under sustained contention (e.g. many parallel submissions or a slow disk) writers can surface `database is locked` after 5s — surfaced as raw sqlite3 exceptions, not `BridgeError`s.
- **Why it matters:** Random-looking failures under load; sqlite3 exceptions bypass the bounded error-JSON envelope the CLI otherwise guarantees (unless caught broadly in `main()`).
- **Evidence:** `db/connection.py` — PRAGMA list omits busy_timeout; `task/store.py submit`, `resource/store.py put_bytes`, `task/runtime_store.py` — `BEGIN IMMEDIATE` usage; `task/runtime.py` — claim loop continuously transacts.
- **Expected impact:** Sporadic `sqlite3.OperationalError: database is locked` in worker or CLI during bursts; potential claim/submit retry churn.
- **Trigger conditions:** ≥3 processes writing tasks.db concurrently with transactions lasting seconds (Windows AV scanning, WAL checkpoint stalls) or heavy submission volume.
- **Suggested verification direction:** Hammer test: N parallel `task submit` while a worker runs; watch for OperationalError. Set explicit `busy_timeout` (e.g. 30–60s) and map `OperationalError` to a `BridgeError` subtype.

### [ ] C8. sqlite-vec KNN applies `k` before WHERE filters — namespace/entry-filtered dense searches can silently return fewer (or zero) results

- **Severity:** Medium
- **Confidence:** Plausible candidate
- **Affected:** `src/houbridge/search/dense.py` (`SQLiteVecIndex.search` — `embedding MATCH ? AND k = ?` plus `namespace IN …` / entry-id temp table)
- **Description:** sqlite-vec's `k = ?` constraint bounds the KNN *before* the remaining WHERE terms are applied (a known property of vec0 virtual tables: the k-nearest neighbors are computed first, then filtered). A filtered search can therefore return fewer than `top_k` results even when more qualifying rows exist below the global top-k cutoff; matches unique to a small namespace may be missed entirely.
- **Why it matters:** Silent recall loss in exactly the scenario filters exist for (script_search reconciliation with a current-id filter; live-search namespace scoping). Results look plausible, so users won't know anything was dropped.
- **Evidence:** `search/dense.py` — single query combining `embedding MATCH ? AND k = ?` with `namespace IN (?)` and optional `entry_id IN (SELECT …)` filter; no over-fetch + re-rank. `live_code_search/ranking.py` mitigates via `candidate_limit` (over-fetch), but script_search passes the full current-id list where the starvation window is narrow yet real during partial reconciliation.
- **Expected impact:** Missing search hits in filtered dense/hybrid searches; degraded RRF quality when the dense leg returns a short list.
- **Trigger conditions:** Vector table containing many rows across namespaces/entry sets where qualifying matches rank below the global top-k for the query.
- **Suggested verification direction:** Insert 1000 vectors in namespace B near a decoy set in namespace A; search with `namespace = B`, small k; compare against brute-force filtered top-k. Fix direction: k' = k * estimated_selectivity over-fetch, or per-namespace indexes.

### [ ] C9. Supervisor/worker ownership handoff race causes transient worker churn

- **Severity:** Low
- **Confidence:** Plausible candidate
- **Affected:** `src/houbridge/task/supervisor.py` (`ensure_active`); `src/houbridge/task/activation.py` (launcher handshake); `src/houbridge/task/runtime_store.py` (`reserve_runtime_start` / `claim_runtime_owner`)
- **Description:** If the reserving starter process dies while the worker is still starting, `ensure_active` observes a dead starter identity, clears the ownership row, and may reserve again and launch a second worker; the first worker's `claim_runtime_owner` then fails and it exits. The system self-heals (claims are re-adoptable), but duplicate worker spawns and wasted dispatches can occur during the window.
- **Why it matters:** Mostly cosmetic churn; but a second Houdini dispatch target lock (`ManagedExecutionLock` per identity) can briefly contend, and logs show confusing ownership flips.
- **Evidence:** `supervisor.py` — liveness checked via starter identity before worker registers its own identity; `activation.py` — polls until `runtime_identity` present, else terminate; `runtime_store.py` — `claim_runtime_owner` requires matching token.
- **Expected impact:** Occasional duplicate worker process for seconds; no task loss (recovery/adoption paths verified safe).
- **Trigger conditions:** CLI process that triggered worker spawn dies within the launch/poll window.
- **Suggested verification direction:** Kill the submitting CLI immediately after submit; trace ownership rows and worker processes over the next seconds. Consider a short grace period before clearing rows whose starter died but whose token lacks runtime_identity.

---

## Investigation leads

### [ ] C10. `_read_toml_cached` returns shared nested dicts — future mutation corrupts the cross-call cache

- **Severity:** Low
- **Confidence:** Investigation lead
- **Affected:** `src/houbridge/config.py` (~lines 265–289, lru_cache(32) keyed on path/mtime/size/sha256)
- **Description:** `_deep_merge` shallow-copies only the top level; nested tables remain references into the cached parsed document. Current callers treat settings as read-only (verified), but any future in-place mutation of a nested table would silently corrupt subsequent `load_config()` results process-wide.
- **Why it matters:** Latent footgun; defeats the mtime-keyed cache's correctness assumptions.
- **Evidence:** Source inspection of `_read_toml_cached` + `_deep_merge`.
- **Expected impact:** None today; future bug class.
- **Trigger conditions:** A caller mutating nested config values in place.
- **Suggested verification direction:** Add a cheap defensive deep-copy at the merge boundary or a test asserting cached immutability.

### [ ] C11. `append_transport_chunk` silently drops chunks on offset CAS mismatch

- **Severity:** Low
- **Confidence:** Investigation lead
- **Affected:** `src/houbridge/task/invocation_store.py` (`append_transport_chunk`); caller `src/houbridge/task/streaming.py` (return value ignored)
- **Description:** The offset compare-and-set returns the current offset without appending when `current_offset != expected_offset`; the caller ignores the return value, so a conflicting append silently discards that chunk's committed bytes. Under the intended single-writer-per-invocation model this is unreachable (offset is re-read each drain), but nothing enforces the invariant — e.g. two recovered workers both adopting a claim would truncate output silently rather than error.
- **Why it matters:** Violations of the single-writer assumption degrade into data loss, not diagnostics.
- **Evidence:** `invocation_store.py` CAS branch; `streaming.py` drain loop ignoring the returned offset.
- **Expected impact:** Missing stream tail in rare duplicate-monitor scenarios.
- **Trigger conditions:** Concurrent drains of the same invocation (should be prevented by claim adoption, which deletes other-owner claims for running tasks).
- **Suggested verification direction:** Prove uniqueness: adoption removes competing claims for running tasks; add an assertion/log when CAS misses.

### [ ] C12. `session new` can leave `primary = None` when the previous primary went stale but the registry file already existed

- **Severity:** Low
- **Confidence:** Investigation lead
- **Affected:** `src/houbridge/session/new.py` (`create`)
- **Description:** Primary is auto-set only when the registry file did not previously exist. If a registry exists whose primary is stale, `cleanup_locked` nulls the primary, the new session is added, and primary stays `None` — even if it's now the only live session. Subsequent implicit-session commands fail with `session_primary_missing` until the user runs `session promote`.
- **Why it matters:** Surprising UX: "I created a session" doesn't imply "the CLI will use it", specifically in the stale-primary recovery scenario where the user is most likely to just create a new one.
- **Evidence:** `session/new.py` — `if not registry_existed: primary = number`; `session/stale.py cleanup_locked` nulls primary when stale.
- **Expected impact:** Extra manual promote step; possible perception that session creation half-failed.
- **Trigger conditions:** Registry exists, its primary is dead, user runs `session new`.
- **Suggested verification direction:** Confirm intended semantics with design docs; if undesired, auto-promote when cleanup leaves zero live sessions.

### [ ] C13. `resource_semantic_aliases` rows are orphaned forever by TTL cleanup

- **Severity:** Low
- **Confidence:** Investigation lead
- **Affected:** `src/houbridge/resource/schema.py`; `src/houbridge/resource/store.py` (`cleanup_expired`)
- **Description:** No FK between aliases and resources; cleanup deletes only `resources` rows, leaving alias rows (prefix + ordinal + canonical_id) accumulating without bound. Possibly intentional (alias stability / ordinal non-reuse), but nothing documents that, and `MAX(ordinal)+1` allocation makes the table grow monotonically.
- **Why it matters:** Unbounded slow growth in a TTL-ed store; future confusion about whether aliases are garbage-collectable.
- **Evidence:** Schema lacks FK; cleanup statement deletes from `resources` only.
- **Expected impact:** Negligible near-term; unbounded row growth over months of use.
- **Trigger conditions:** Normal operation with resource TTL cleanup enabled.
- **Suggested verification direction:** Decide and document alias lifetime; if kept forever, cap ordinal reuse semantics in docs; consider deleting aliases whose canonical_id has no live resource after a grace period (breaking change — needs product decision).

### [ ] C14. ActionRecorder takes a full-scene baseline snapshot on every recorded execution

- **Severity:** Low (perf)
- **Confidence:** Investigation lead
- **Affected:** `src/houbridge/houdini/scripts/history/action_recorder.py`
- **Description:** Baseline iterates `allSubChildren()` plus all parms' `rawValue()` for the whole scene on each prepare — O(scene) work per exec inside Houdini. On heavy scenes (100k+ nodes) with default-on history, every `houbridge exec` pays a full scene traversal that scales with scene size, not with the change the script makes.
- **Why it matters:** Latency ceiling on the primary command; users will disable history to compensate, losing the feature.
- **Evidence:** Baseline construction in `action_recorder.py` (full snapshot before install); no dirty-region or lazy baseline strategy.
- **Expected impact:** Multi-second overhead per exec on large scenes.
- **Trigger conditions:** History enabled (default) + large scenes.
- **Suggested verification direction:** Time exec prepare on a heavy scene; consider lazy baselining (snapshot only nodes touched, keyed by generation) or event-driven diffing.

### [ ] C15. ffmpeg encode runs without a timeout

- **Severity:** Low
- **Confidence:** Investigation lead
- **Affected:** `src/houbridge/capture/ffmpeg.py` (`subprocess.run` no timeout)
- **Description:** Turntable encoding waits on ffmpeg indefinitely. Frame-heavy turntables on slow disks/CPUs hold the CLI for as long as ffmpeg runs; a wedged ffmpeg (rare) hangs the command forever.
- **Why it matters:** Unbounded CLI latency; no cancel path.
- **Evidence:** `subprocess.run(...)` call without `timeout=`; rc/stderr handled properly otherwise.
- **Expected impact:** Long (or infinite) hangs on pathological encodes.
- **Trigger conditions:** Large `frames` × resolution, or ffmpeg stall.
- **Suggested verification direction:** Add a generous timeout derived from frame count, and a clear error including partial output path.

### [ ] C16. macOS has no standard-roots installation discovery

- **Severity:** Low
- **Confidence:** Investigation lead
- **Affected:** `src/houbridge/houdini/installations.py`
- **Description:** Discovery roots cover Windows Program Files and Linux `/opt`/`HFS`/PATH, but Darwin scans nothing (`/Applications/Houdini*` absent) — default installs aren't found unless `HFS` is set or the executable is configured/explicit.
- **Why it matters:** First-run macOS experience: session launch requires manual configuration.
- **Evidence:** Roots list in `installations.py` per-OS branches.
- **Expected impact:** `houdini_install_not_found` on stock macOS setups.
- **Trigger conditions:** macOS, no `HFS`, no configured executable.
- **Suggested verification direction:** Add `/Applications` + `/Applications/Houdini/HoudiniXX.Y.Z` glob patterns behind the existing version-sort logic.

### [ ] C17. Contentless FTS5 with `contentless_delete=1` requires SQLite ≥ 3.43

- **Severity:** Low
- **Confidence:** Investigation lead
- **Affected:** `src/houbridge/search/lexical.py`
- **Description:** The schema uses `contentless_delete=1`; older/bundled SQLite builds (some system Pythons, frozen apps shipping old sqlite3) fail on DELETE from contentless FTS5 tables, breaking upsert/reconcile on those runtimes.
- **Why it matters:** Portability failure that appears only on specific interpreter builds.
- **Evidence:** DDL in `lexical.py`; SQLite 3.43 changelog introduced `contentless_delete`.
- **Expected impact:** `sqlite3.OperationalError` on first reconcile for affected builds.
- **Trigger conditions:** Python with sqlite3 < 3.43 (check `sqlite3.sqlite_version` at runtime).
- **Suggested verification direction:** Feature-detect at startup (`sqlite3.sqlite_version_info`) and fall back to regular (contentful) FTS5 or plain LIKE index.

### [ ] C18. Test suite is non-hermetic (reads the machine's real global config) and has 3 Windows-specific defects

- **Severity:** Medium (engineering hygiene)
- **Confidence:** High-confidence candidate (as a test-infra finding; product impact nil)
- **Affected:** `tests/unit/test_output_policy.py`, `tests/unit/test_resource_cli.py`, `tests/unit/test_session_cli.py`, `tests/unit/test_task_completion_cli.py` (config bleed); `tests/unit/test_config.py::test_global_data_dir_is_expanded`; `tests/unit/test_task_stream_recovery.py` (2 tests)
- **Description:** (a) CLI tests invoke commands whose `load_config()` reads the machine's real `…\houbridge\houbridge\config.toml` — on this machine it holds a legacy schema, producing 6 failures that follow the dev machine, not the commit; `LOCALAPPDATA`/`APPDATA` overrides do not redirect platformdirs 4.11 home-derived paths. (b) `test_global_data_dir_is_expanded` monkeypatches `HOME`, but Windows `ntpath.expanduser` uses `USERPROFILE` — test bug, product behavior correct. (c) Two stream-recovery tests write fixture streams with `write_text` without `newline=""`, so Windows CRLF translation corrupts expected bytes (`'done\r\n' != 'done\n'`) — test bug; product passes bytes through correctly.
- **Why it matters:** Red/green outcomes depend on the host machine's config file and OS; masked real failures and eroded trust in the suite (9 failed / 434 passed at review time, all 9 decomposed to environment, none to product regressions).
- **Evidence:** Test run output + per-failure traces during review; env-override experiment documented above.
- **Expected impact:** CI/local divergence; genuine config bugs could hide among expected failures.
- **Trigger conditions:** Running pytest on Windows with a machine-global config whose schema differs from the current one; running on Windows at all (3 tests).
- **Suggested verification direction:** Inject a temp config path env var honored by `default_config_path()` (product hook needed or monkeypatch fixture in CLI tests); fix `USERPROFILE` patch and `newline=""` in fixtures.

### [ ] C19. Successful GUI session launch never waits the launched Popen

- **Severity:** Low
- **Confidence:** Investigation lead
- **Affected:** `src/houbridge/session/launcher.py` (`launch` success path)
- **Description:** On success the `Popen` handle for Houdini is dropped without `wait()`/detach bookkeeping. On POSIX, if the CLI process lives long enough, the child shows as a zombie until CLI exit; also `ResourceWarning` under `-W error` in tests.
- **Why it matters:** Cosmetic/process-table noise; can confuse tooling that scans for zombies.
- **Evidence:** Success return path in `launcher.py`; failure path carefully terminates — success path has no reaping.
- **Expected impact:** Transient zombie entries; no functional harm (bootstrap pid handles liveness separately).
- **Trigger conditions:** POSIX, GUI launch, long-lived CLI process.
- **Suggested verification direction:** `Popen.poll()`-and-release or double-fork style detach; verify no zombies after `session new` on Linux.

---

## Test-suite evidence summary

`uv run --extra test pytest` at `dd6e9cf`: **9 failed, 434 passed**. All 9 decomposed to environment/test defects (6 × machine-global legacy config bleed — see C4/C18; 1 × HOME vs USERPROFILE; 2 × Windows newline translation), none to product regressions on this commit.

## Overengineering / complexity observations (no defect alleged)

- `history/store.py initialize()` re-runs the full schema executescript + metadata upsert on every `allocate_id`/`embed_source` call — correct but heavyweight; a per-connection initialized flag would remove redundant DDL parsing.
- `history/search.py _synchronize_indexes` rebuilds dense+lexical indexes on every search — O(entries) per query; acceptable now, worth indexing-on-write later.
- `output/policy.py render` re-serializes the payload twice (cost only).
