# Remove Capture OCR

## Why

OCR is not Houdini-specific capture behavior. Keeping OCR inside Houbridge makes the Capture subsystem own an unrelated recognition runtime, model cache, result-normalization contract, and heavy RapidOCR/ONNX dependencies. The standalone `image-ocr` tool now owns image text recognition, so Houbridge should return to producing capture artifacts only.

## What Changes

- Remove the public `houbridge capture ocr IMAGE` command.
- Remove Houbridge's embedded OCR service, OCR result formatting, OCR model/cache handling, and OCR-specific errors/tests.
- Remove RapidOCR and ONNX Runtime dependencies when no remaining Houbridge subsystem requires them.
- Remove OCR-specific Output Policy examples while preserving the shared Output Policy itself.
- Keep viewport, window, camera, pane discovery, and turntable capture behavior unchanged.
- Do not add an `image-ocr` wrapper or delegation path inside Houbridge. Callers that need OCR compose `houbridge capture ...` and `image-ocr IMAGE` explicitly.

## Impact

### Modified capabilities

- `capture`: removes OCR recognition ownership and leaves image/video capture responsibilities only.
- `command-capture`: removes the public OCR subcommand and its response contract.
- `output-policy`: removes the OCR-specific Resource-fallback scenario; the generic shared fallback remains unchanged.

### Code and dependency impact

Expected implementation work includes `src/houbridge/capture/ocr.py`, Capture exports, capture CLI registration, OCR tests, documentation/skills that advertise OCR, and package dependencies used only by embedded OCR.
