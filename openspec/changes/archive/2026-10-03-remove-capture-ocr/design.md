# Design: Remove Capture OCR

## Context

Houbridge currently owns both Houdini capture production and general-purpose image OCR. The OCR path accepts an arbitrary image, initializes RapidOCR with ONNX Runtime and PP-OCRv6 models, normalizes recognition results into a text-indexed mapping, and exposes that behavior through `houbridge capture ocr`.

That behavior does not depend on a Houdini session or Houdini capture internals. A standalone `image-ocr` CLI now provides the OCR responsibility independently.

## Goals

- Remove OCR as a Houbridge public feature.
- Remove OCR runtime/model/result-formatting ownership from the Capture subsystem.
- Remove dependencies that exist solely for embedded OCR.
- Preserve all non-OCR Capture behavior.
- Keep the boundary explicit: Houbridge produces images; another tool may inspect those images.

## Non-goals

- Houbridge will not invoke `image-ocr` internally.
- Houbridge will not preserve `houbridge capture ocr` as a compatibility wrapper.
- Houbridge will not define or translate the standalone OCR JSON schema.
- This change does not alter viewport, window, camera, pane discovery, or turntable capture contracts.

## Dependency direction

After this change, Houbridge has no dependency on an OCR application or OCR model runtime for Capture.

Composition remains external to Houbridge:

```text
houbridge capture ... -> image file
image-ocr IMAGE       -> OCR JSON
jq                    -> optional filtering
```

The three commands are independently owned interfaces. Houbridge does not inspect, proxy, or transform `image-ocr` output.

## Removal boundary

Implementation should remove the OCR command registration and the OCR-only Capture implementation rather than leaving dead compatibility code. OCR-only package dependencies should be removed only after confirming they are unused by every other Houbridge subsystem.

Tests should prove both sides of the boundary:

- OCR is no longer exposed by the Houbridge CLI.
- Existing non-OCR capture commands continue to behave as specified.

## Specification maintenance

The existing `capture` and `command-capture` Purpose summaries mention OCR. OpenSpec delta operations do not update Purpose for an existing capability, so those Purpose summaries must be updated directly when the removal is synchronized/archived so the resulting main specs do not continue to describe OCR as part of Houbridge.

Synchronize `add-exec-full-transport` first. This removal's `output-policy` replacement must preserve the bounded Resource-inspection exception, synchronous `exec --full` exception, and complete-transport scenario from that change. OpenSpec validates `MODIFIED` requirements against all current baseline scenarios; delete only the obsolete `A large OCR result is produced` baseline scenario directly before strict validation, then leave the OCR requirement removals to this change's validated archive.
