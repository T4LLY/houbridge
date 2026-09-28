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
- [ ] 3.3 Refresh the dependency lockfile and verify a clean install/test run.

## 4. Preserve Capture behavior

- [ ] 4.1 Run Capture tests for pane discovery, viewport, window, camera, and turntable behavior.
- [ ] 4.2 Verify capture artifacts remain usable as ordinary image/video files with no OCR coupling.

## 5. Update project documentation

- [ ] 5.1 Remove README and skill references that advertise Houbridge OCR.
- [ ] 5.2 After spec synchronization/archive, update the existing `capture` and `command-capture` Purpose summaries so they no longer mention OCR.

## 6. Final verification

- [ ] 6.1 Run the relevant test suite and confirm no OCR implementation, command registration, or OCR-only dependency remains.
- [ ] 6.2 Validate the OpenSpec change and resulting specifications.
