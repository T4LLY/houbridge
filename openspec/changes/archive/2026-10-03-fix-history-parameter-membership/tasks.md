Approved implementation scope, parent verification, strict validation, baseline-spec validation, and archive are complete: net parameter-membership compaction, nullable-side validation/materialization, and persistence/read/search coverage. Native Houdini event delivery and broader spare/multiparm capture remain unverified and deferred; this change does not claim that all such membership changes are captured.

## 1. Focused Contract Regressions

- [x] 1.1 Extend `tests/unit/test_history_action_recorder.py` with the eight existing/created × add/remove × empty/non-empty cases using whole-node parameter callbacks; cover membership return-to-baseline, different-value re-add, created initial-parameter suppression, final paths, and deletion/transience controls.
- [x] 1.2 Extend `tests/unit/test_history_changes.py` for both null-side orientations, genuine empty strings, required/exact keys, both-null rejection, and non-string/non-null raw rejection. Cover 4096-byte and oversized UTF-8 present sides opposite null, including multibyte strings, exact Resource bytes/classification/token metadata, and no Resource writes for absent/empty sides.

## 2. Recorder and Host Implementation

- [x] 2.1 Update shared `_parm_changes` in `src/houbridge/houdini/scripts/history/action_recorder.py` to compare sorted union keys and preserve missing sides as null, retaining each node cohort's existing baseline and node compaction/path semantics.
- [x] 2.2 Update parameter-side types, validation, bounding, and serialization in `src/houbridge/history/changes.py` to support `str | None` raw sides and `str | None | OmittedRawValue` materialized sides; preserve exact-key validation and reject both-null/unsupported raw values as `history_change_invalid`.

## 3. Persistence, Read, Search, and Verification

- [x] 3.1 Add focused regressions in the existing History storage/search tests that commit materialized membership changes, read them through the public get service, and verify null/empty/Resource sides and exact keys; verify parameter-name/final-path lexical recall without inventing null terms or loading omitted bodies.
- [x] 3.2 Run the installed test environment against `tests/unit/test_history_action_recorder.py`, `test_history_changes.py`, `test_history_storage.py`, `test_history_search.py`, `test_history_sync_execution.py`, `test_history_async_task.py`, and `test_history_lifecycle.py`; confirm the focused membership/contract regressions and preserved baseline controls pass.
- [x] 3.3 Parent reviewed the final implementation and both deltas; strict validation passed. Confirmed standard JSON persistence requires no SQL migration and clients receive the approved null representation. Native event delivery is explicitly outside the verified scope (see residual limitation below).

## 4. Local Evidence

- Verified base HEAD: `70839fc`. Both production files had an empty diff at the tests-first red run.
- Red, four changed History test suites: **36 failed, 76 passed**. Eight failures demonstrated recorder omissions; sixteen exercised valid nullable raw/Resource sides, eight exercised capture/storage/public/projection round trips, and four exercised lexical recall. All failures matched the approved behavior gap.
- Green, the same four suites plus existing sync/async/lifecycle suites: **132 passed**.
- Both runs used `.venv/Scripts/python.exe -B -m pytest -p no:cacheprovider --tb=line` with external basetemps `D:/Temp/opencode/hb02-native-red-70839fc` and `D:/Temp/opencode/hb02-native-green-70839fc` respectively.
- Local strict validation: `openspec validate fix-history-parameter-membership --type change --strict --no-interactive --json` — **1 passed, 0 failed, zero issues**. Native `hou` is unavailable; fake-Houdini recorder/capture tests assume callback delivery, while Resource and History persistence use real SQLite.
- Parent verification (base `70839fc`): `uv run --frozen --no-sync --no-python-downloads python -B -m pytest -p no:cacheprovider --basetemp D:\Temp\opencode\hb02-parent-final-70839fc tests/unit/test_history_action_recorder.py tests/unit/test_history_changes.py tests/unit/test_history_storage.py tests/unit/test_history_search.py tests/unit/test_history_sync_execution.py tests/unit/test_history_async_task.py tests/unit/test_history_lifecycle.py` — **132 passed in 4.76s**. Parent also ran strict change validation in JSON mode (**1 passed, zero issues**) and scoped `git diff --check` (passed).
- Independent reviewer also ran the same 132 focused tests (**132 passed**) and found no semantic blocker within the approved compactor/null contract.
- Native Houdini event delivery is unverified. Fake `ParmTupleChanged` calls are a callback-delivery assumption, not native-event evidence. Houdini [documents `SpareParmTemplatesChanged`](https://www.sidefx.com/docs/houdini/hom/hou/nodeEventType.html) for spare-parameter add/remove; multiparm membership delivery is not established as silent or complete under the current subscription. Do not claim all spare/multiparm membership changes are captured. Native delivery investigation and any subscription expansion are deferred follow-up work; event-subscription expansion remains outside this change's scope.
- Baseline specs: `openspec validate history --type spec --strict --no-interactive --json` and `openspec validate command-history --type spec --strict --no-interactive --json` — both passed; only informational long-requirement notices were reported.
- Archived-task hygiene: `openspec validate --archived --strict --no-interactive --json` — **3 archived changes passed, 0 failed**.
- Archive command: `openspec archive fix-history-parameter-membership --yes --json` (normal validation enabled; no `--no-validate` or `--skip-specs`); archived as `2026-10-03-fix-history-parameter-membership`, updating 3 spec requirements.
- The archive destination did not exist beforehand. Other unarchived changes are `add-synchronous-file-import-root`, `reimplement-current-specs`, and `restore-hidden-exec-code`; their change folders were not edited. The History capability file has a distinct `restore-hidden-exec-code` requirement; this archive applied only the two approved HB02 History requirements and the command-history public-entry requirement, with no reported overwrite or collision.
