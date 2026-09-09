# Capture Feature Specification

## Purpose

Define viewport inspection, viewport/window screenshots, OCR, and turntable capture while preserving the user's Houdini viewer state and keeping temporary image output bounded. Command JSON schemas are specified separately.

## Requirements

### Requirement: Report visible Scene Viewer viewports

Capture SHALL be able to inspect the currently visible Scene Viewer viewports and report only stable public viewport information needed by callers.

#### Scenario: A quad Scene Viewer is visible
- **WHEN** viewport inspection runs against a quad layout
- **THEN** each visible viewport is reported with its public name/type and pixel dimensions
- **AND** internal Houdini objects or implementation-only state are not required by the caller

#### Scenario: No Scene Viewer is available
- **WHEN** no usable Scene Viewer exists
- **THEN** viewport inspection reports a structured missing-viewer failure

### Requirement: Capture the active viewport

Capture SHALL be able to write a PNG representing the active Scene Viewer viewport.

#### Scenario: Capture a viewport frame
- **WHEN** a normal viewport capture is requested
- **THEN** a completed PNG is published in the operating-system temporary capture area
- **AND** the user's active viewer remains usable after capture

### Requirement: Capture directed views without modifying the user's viewer

Directed captures SHALL use a temporary/cloned Scene Viewer state rather than permanently changing the user's current viewer. Supported directed capture behavior SHALL provide front, right, back, left, top, bottom, and perspective-style view handling where applicable.

#### Scenario: Capture a front view
- **WHEN** a front-directed capture is requested
- **THEN** the temporary capture viewer is aligned to the requested direction
- **AND** the user's original viewer orientation is not changed

#### Scenario: Capture several explicit views
- **WHEN** multiple directed views are requested
- **THEN** each requested view is captured independently
- **AND** completion of one view does not mutate the user's live Scene Viewer state for the next

### Requirement: Capture a fixed captioned quad image

Capture SHALL support a fixed four-view quad reference image with readable view captions.

#### Scenario: Capture quad reference views
- **WHEN** quad capture is requested
- **THEN** the defined four reference views are captured and composed into one image
- **AND** each quadrant is captioned with its view identity

### Requirement: Apply reusable display presets

Viewport and permitted window capture paths SHALL support reusable screenshot display presets for shading, overlays, and attribute visualization. Unknown preset settings SHALL fail explicitly rather than being ignored silently.

#### Scenario: Inspect geometry with a preset
- **WHEN** a supported preset is requested
- **THEN** the temporary capture viewer applies the requested shading/overlay/attribute settings before capture
- **AND** the user's original viewer remains unchanged

#### Scenario: Preset contains an unknown setting
- **WHEN** preset parsing encounters an unsupported key or value
- **THEN** Capture rejects the preset as invalid

### Requirement: Scale before enforcing maximum dimensions

Requested screenshot scale SHALL be applied before clamping to configured maximum width and height. Aspect ratio SHALL be preserved.

#### Scenario: Requested scale exceeds image budget
- **WHEN** scale would produce an image larger than configured maximum dimensions
- **THEN** Capture computes the scaled size first
- **AND** reduces it to fit the configured maximum dimensions without stretching aspect ratio

### Requirement: Capture the Houdini main window

Capture SHALL be able to capture the Houdini main application window through the supported operating-system/window capture path.

#### Scenario: Capture the main UI
- **WHEN** a window capture is requested without a crop selector
- **THEN** the published PNG represents the Houdini main window

### Requirement: Emit image-relative UI bounds for window capture

Window capture SHALL be able to collect pane/tab or Scene Viewer viewport bounds and transform them into coordinates relative to the final published image, accounting for native window coordinates, DPI conversion, crop, and resize.

#### Scenario: Window screenshot is resized
- **WHEN** a captured window image is resized before publication
- **THEN** associated bounds describe locations in the final image coordinate space

### Requirement: Crop a window capture to one supported UI region

Window capture SHALL support selecting one pane tab such as a Network Editor or one Scene Viewer viewport when the selector resolves unambiguously. Ambiguous selectors SHALL fail rather than selecting an arbitrary region.

#### Scenario: Crop a Network Editor
- **WHEN** the crop selector resolves to one Network Editor pane tab
- **THEN** the final image is cropped to that pane's image-relative bounds before final resize

#### Scenario: Crop a Scene Viewer viewport
- **WHEN** the crop selector resolves to one viewport
- **THEN** the final image is cropped to that viewport's bounds

#### Scenario: Crop selector is ambiguous
- **WHEN** more than one visible region satisfies the selector
- **THEN** Capture reports ambiguity and does not guess

### Requirement: Reject unsupported preset/crop combinations

Capture SHALL reject preset or crop combinations that the selected capture mode cannot apply correctly.

#### Scenario: Viewport capture receives a window-only crop preset
- **WHEN** a crop selector is supplied to a capture mode that cannot honor it
- **THEN** Capture rejects that combination

#### Scenario: Turntable receives view/crop preset options
- **WHEN** turntable capture is asked to use unsupported directed-view or crop behavior
- **THEN** Capture rejects that combination before frame production

### Requirement: Use operating-system temporary storage

Screenshot and turntable image outputs SHALL be published below the operating-system temporary directory and returned as filesystem paths according to the Capture command contracts.

#### Scenario: Screenshot succeeds
- **WHEN** a PNG is published
- **THEN** its default capture location is in the operating-system temporary area

### Requirement: Use readable sequential screenshot filenames

Screenshot filenames SHALL use the readable `kind + minute + sequence` convention so multiple captures are easy to distinguish without opaque random names.

#### Scenario: Multiple viewport captures occur in one minute
- **WHEN** more than one viewport capture is published during the same minute
- **THEN** each receives a distinct monotonically sequenced filename for that kind/minute

### Requirement: Publish only completed capture files

Capture SHALL not expose partially written PNGs as successful output. Temporary/in-progress files SHALL be finalized atomically or otherwise withheld until complete.

#### Scenario: Capture fails during image production
- **WHEN** the capture pipeline fails before a valid PNG is complete
- **THEN** no incomplete final PNG is advertised as successful

### Requirement: Expire temporary screenshots lazily

Capture SHALL lazily remove expired Houbridge-created screenshot files according to configured retention. Cleanup SHALL target Houbridge's known temporary naming/layout and SHALL not delete a screenshot that the user copied or moved elsewhere.

#### Scenario: A screenshot command runs
- **WHEN** Capture starts a new screenshot operation
- **THEN** expired Houbridge capture files in the managed temporary area may be reclaimed

#### Scenario: A screenshot was moved elsewhere
- **WHEN** a prior image no longer resides in the managed temporary capture location
- **THEN** cleanup does not chase and delete the moved copy

### Requirement: Preserve window-bounds sidecar lifecycle

When window capture produces bounds metadata, the sidecar SHALL be published and expired with the corresponding managed screenshot.

#### Scenario: Window bounds are produced
- **WHEN** a window capture has UI bounds metadata
- **THEN** the bounds sidecar is written next to the managed screenshot
- **AND** cleanup can remove both once expired

### Requirement: Extract OCR text and compact bounding boxes

OCR SHALL accept an existing image path, run detection and recognition, normalize line breaks in recognized text, group duplicate recognized strings, and represent each occurrence with recognition score when available plus a compact axis-aligned bounding box.

#### Scenario: Recognize screenshot text
- **WHEN** OCR finds a text polygon
- **THEN** the recognized text is normalized to one line
- **AND** the polygon is reduced to integer `[min_x, min_y, max_x, max_y]` bounds

#### Scenario: Same text occurs multiple times
- **WHEN** identical normalized text appears at several locations
- **THEN** all occurrences are retained under that text rather than overwriting one another

#### Scenario: OCR finds no text
- **WHEN** the engine returns no boxes
- **THEN** OCR succeeds with an empty recognition mapping

#### Scenario: OCR receives a missing image
- **WHEN** the input image does not exist
- **THEN** OCR fails before initializing the OCR runtime

### Requirement: Keep OCR runtime quiet and cache models predictably

OCR engine initialization SHALL suppress library progress/noise that would corrupt machine-readable CLI output. OCR model assets SHALL use the standard Hugging Face assets cache hierarchy, including `HF_ASSETS_CACHE`, `HF_HOME`, and `XDG_CACHE_HOME` precedence before the normal user cache fallback.

#### Scenario: OCR initializes models
- **WHEN** the OCR runtime is first constructed
- **THEN** initialization does not emit uncontrolled progress output to stdout/stderr
- **AND** model assets are placed under the selected shared cache root

### Requirement: Use the defined OCR engine profile

The default OCR runtime SHALL use RapidOCR with ONNX Runtime for detection and recognition, tiny PP-OCRv6 detection/recognition models, and classification disabled for the recognition call.

#### Scenario: Build the default OCR engine
- **WHEN** no injected test engine is supplied
- **THEN** RapidOCR uses ONNX Runtime for detection and recognition
- **AND** the tiny PP-OCRv6 detection and recognition models are selected

### Requirement: Route oversized OCR results through the common Output Policy

OCR SHALL return its complete logical recognition result to the common Output subsystem. OCR-specific code SHALL NOT implement an independent output token threshold.

#### Scenario: OCR recognizes a very large amount of text
- **WHEN** the logical OCR result exceeds the common inline budget
- **THEN** the common Output subsystem Resource-backs the oversized result

### Requirement: Capture a turntable image sequence

Turntable capture SHALL clone the relevant viewer state, rotate a perspective capture camera/view around a world-space pivot, and publish a sequence of completed PNG frames at the requested frame count and frame rate.

#### Scenario: Capture a turntable
- **WHEN** a turntable is requested without an explicit pivot
- **THEN** Capture derives the normal capture pivot and rotates around it
- **AND** frame numbering is deterministic for later encoding

#### Scenario: Capture around an explicit pivot
- **WHEN** the caller supplies three finite world-space coordinates
- **THEN** those coordinates are used as the turntable pivot

#### Scenario: Reject an invalid pivot
- **WHEN** the pivot does not contain exactly three finite numbers
- **THEN** Capture rejects the request before frame capture

### Requirement: Apply turntable scale before maximum dimensions

Turntable frame dimensions SHALL follow the same scale-then-clamp rule as screenshot capture.

#### Scenario: Turntable scale exceeds configured dimensions
- **WHEN** requested scale would make frames exceed configured width/height
- **THEN** final frames are reduced within the configured budget while preserving aspect ratio

### Requirement: Optionally encode turntable frames with ffmpeg

Turntable capture SHALL optionally encode the preserved PNG sequence using `ffmpeg`. Missing or failed `ffmpeg` SHALL not destroy already completed source frames. H.264 encoding SHALL pad odd frame dimensions as necessary rather than rejecting otherwise valid captures.

#### Scenario: ffmpeg is unavailable
- **WHEN** video encoding is requested but `ffmpeg` cannot be run
- **THEN** Capture reports the encoding failure while preserving the completed PNG sequence

#### Scenario: Accepted frame dimensions are odd
- **WHEN** H.264 encoding receives an odd width or height
- **THEN** the encoding path pads to valid dimensions without changing the source frame files

### Requirement: Keep injected Capture code under the Capture script boundary

Houdini-side viewport/window/turntable implementation SHALL be grouped below `houbridge/houdini/scripts/capture/`, with common display/view helpers factored there rather than duplicated as large host-side source strings.

#### Scenario: Screenshot and turntable share viewer helpers
- **WHEN** both features need cloning, sizing, presets, or display logic
- **THEN** shared injected helpers live in focused Capture script modules
- **AND** host-side Capture services remain orchestration-focused
