# Tasks

## 1. Remove the public OCR command

- [x] 1.1 Remove `houbridge capture ocr IMAGE` registration and OCR-specific CLI wiring.
- [x] 1.2 Remove CLI tests that assert the deleted OCR command and add coverage proving it is no longer exposed.

## 2. Remove embedded OCR ownership

- [x] 2.1 Remove the Capture OCR service and its public exports.
- [x] 2.2 Remove OCR-only result normalization, model/cache handling, runtime-noise suppression, and OCR-specific error paths.
- [x] 2.3 Remove OCR-only tests after preserving any generally useful non-OCR test coverage elsewhere.

## 3. Remove OCR-only dependencies

- [x] 3.1 Trace RapidOCR and ONNX Runtime usage across the repository.
- [x] 3.2 Remove package dependencies that are no longer required by any Houbridge subsystem.
- [x] 3.3 Refresh the dependency lockfile and verify a clean install/test run.

## 4. Preserve Capture behavior

- [x] 4.1 Run Capture tests for pane discovery, viewport, window, camera, and turntable behavior.
- [x] 4.2 Verify capture artifacts remain usable as ordinary image/video files with no OCR coupling.

## 5. Update project documentation

- [x] 5.1 Remove README and skill references that advertise Houbridge OCR.
- [x] 5.2 After spec synchronization/archive, update the existing `capture` and `command-capture` Purpose summaries so they no longer mention OCR.

## 6. Final verification

- [x] 6.1 Run the relevant test suite and confirm no OCR implementation, command registration, or OCR-only dependency remains.
- [x] 6.2 Validate the OpenSpec change and resulting specifications.

## HB-01 synchronization evidence (2026-10-03)

- Verified `git rev-parse --short=7 HEAD` as `70839fc`. Read both changes' proposals, designs, tasks, and deltas before synchronization.
- `openspec validate add-exec-full-transport --strict --no-interactive --json` passed, then `openspec archive add-exec-full-transport --yes --json` applied one added and nine modified requirements and archived it as `2026-10-03-add-exec-full-transport` with validation enabled.
- Preserved that archive's bounded Resource-inspection and synchronous `exec --full` fallback exceptions in this change's `output-policy` delta. Deleted only the obsolete OCR fallback scenario directly from the baseline to resolve the reproduced strict `MODIFIED`-scenario validation failure. Updated both Capture Purpose summaries directly before the final validated archive removed the four Capture OCR requirements and the public OCR command requirement.
- Exec/Output regression evidence: `.\.venv\Scripts\python.exe -B -m pytest -p no:cacheprovider --basetemp "D:\Temp\opencode\houbridge-hb01-exec-70839fc" tests/unit/test_exec_cli.py tests/unit/test_execution_presentation.py tests/unit/test_output_policy.py tests/unit/test_resource_cli.py tests/unit/test_task_completion_cli.py` passed **52 tests**.
- 4.1 evidence: `.\.venv\Scripts\python.exe -B -m pytest -p no:cacheprovider --basetemp "D:\Temp\opencode\houbridge-hb01-capture-70839fc" tests/unit/test_capture_cli.py tests/unit/test_capture_preset.py tests/unit/test_viewport.py tests/unit/test_screenshot.py tests/unit/test_camera.py tests/unit/test_turntable.py` passed **63 tests**.
- 4.2 evidence: the existing screenshot/camera tests generate standard PNG fixtures, inspect PNG dimensions, and verify publication (including camera PNG byte equality). Turntable tests verify the H.264/yuv420p ffmpeg profile, MP4-only publication, and failure withholding. The deterministic contract trace is `ScreenshotService`/`CameraService` -> `CaptureArtifactPublisher.publish_png` and `TurntableService.capture` -> `encode_turntable_ffmpeg` -> `publish_turntable_mp4` -> byte-preserving `TemporaryArtifactService.publish_file_exact`. Transport/encoder test doubles are used; no live Houdini or video-decoder run is claimed. These paths have no OCR recognition, wrapper, or dependency coupling.
- 5.1 evidence: searches of `README.md` and `skills/` found no OCR advertisements. `src/`, `pyproject.toml`, and `uv.lock` contain no OCR runtime/dependency references; the only OCR references in tests are negative CLI exposure assertions, which passed.
- Pre-archive specification evidence: `openspec validate remove-capture-ocr --strict --no-interactive --json`, strict validation of all six affected baseline specs (`--type spec`), and `openspec validate --archived --strict --no-interactive --json` all passed. Baseline fallback retains Search, Task, and Exec-full scenarios and no OCR scenario. The six baseline checks report informational long-requirement notices only.
- 3.3 parent-owned evidence: with `UV_PROJECT_ENVIRONMENT=D:\Temp\opencode\houbridge-hb01-clean-70839fc`, the parent independently ran `uv sync --locked --extra test` at unchanged source HEAD `70839fc`. A fresh environment was created, 39 packages resolved and 38 installed (including `sqlite-vec==0.1.9`), exit **0**. The parent reported the completed PTY log. Locked synchronization accepted the existing lockfile; this documentation synchronization did not regenerate or edit it.
- 6.1 parent-owned evidence: in that same fresh environment, the parent independently ran `uv run --locked --extra test python -B -m pytest -p no:cacheprovider --basetemp D:\Temp\opencode\houbridge-hb01-clean-tests-70839fc`, exit **0**, **522 passed in 16.75s**. The parent reported the completed PTY log. Combined with the unchanged-source removal trace above, this closes the clean-install/full-suite gates; the focused local tests are separate evidence.
- 6.2 final specification evidence: `openspec validate remove-capture-ocr --strict --no-interactive --json` passed immediately before `openspec archive remove-capture-ocr --yes --json`, which archived this change as `2026-10-03-remove-capture-ocr` with validation enabled and reported **5 removed requirements**, no added/modified requirements. Strict `openspec validate <capability> --type spec --strict --no-interactive --json` passed for `command-contract`, `command-exec`, `execution`, `output-policy`, `capture`, and `command-capture`. Searches of `openspec/specs/` found no OCR references, including no OCR Purpose, requirement, or fallback text. Inspection confirmed the Exec-full per-artifact/whole-result/hard-limit exclusions, `result_kind`, canonical serialization, traceback Resource behavior, and bounded non-full/Resource-inspection paths remain intact. Completed 6.2 after these merged-spec checks; the only spec notices were informational long-requirement messages.
- Final archived-task hygiene: `openspec validate --archived --strict --no-interactive --json` passed both `2026-10-03-add-exec-full-transport` and `2026-10-03-remove-capture-ocr` with no issues. Both archived task lists have no unchecked items; all **14** removal tasks are complete. Scoped `git diff --check` passed, and the tracked report, source/tests, and unrelated change directories have no diff from HEAD. No staging or commit was performed.
