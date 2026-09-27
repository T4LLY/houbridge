# Capture Feature Specification

## Purpose

Define viewport inspection, viewport/window screenshots, OCR, and turntable video capture while preserving the user's Houdini viewer state and keeping temporary image/video output bounded. Command JSON schemas are specified separately.

## Requirements

### Requirement: Report visible Scene Viewer panes and their viewports

Capture SHALL inspect every visible Scene Viewer pane tab returned by Houdini, including visible Scene Viewers in floating windows. Each pane SHALL expose its pane-tab name, current node path when available, and every viewport currently visible in that Scene Viewer. Pane ordering SHALL follow Houdini's enumeration and SHALL NOT carry public ordering semantics. Capture SHALL report only stable public data and SHALL NOT expose Houdini objects or implementation-only state.

`current_node` SHALL be the current node path when it can be obtained and SHALL be `null` when no current node is available or the current node cannot be read safely. Each viewport SHALL contain its public name/type and pixel dimensions. Viewport selection/current-state flags SHALL NOT be part of this catalog.

#### Scenario: Several Scene Viewers are visible
- **WHEN** viewport inspection runs while multiple Scene Viewer pane tabs are visible
- **THEN** every visible Scene Viewer is reported as a separate pane entry
- **AND** each pane contains every viewport currently visible in that Scene Viewer
- **AND** pane ordering does not imply selection priority

#### Scenario: A Scene Viewer has no readable current node
- **WHEN** the Scene Viewer has no current node or its current node cannot be read safely
- **THEN** its `current_node` is `null`

#### Scenario: No Scene Viewer is available
- **WHEN** no usable Scene Viewer exists
- **THEN** viewport inspection reports a structured missing-viewer failure

### Requirement: Capture the active viewport

Capture SHALL be able to write a PNG representing a Scene Viewer viewport. When exactly one visible Scene Viewer exists and no pane is specified, Capture SHALL use it automatically. When more than one visible Scene Viewer exists, Capture SHALL require an explicit pane-tab name and SHALL NOT select one by enumeration order. An explicit pane name SHALL match exactly one visible Scene Viewer pane tab.

Missing and ambiguous pane selection failures SHALL include the same Scene Viewer catalog shape used by viewport inspection under structured error `context.panes`, so callers can retry without issuing a separate inspection request.

#### Scenario: Capture a viewport frame
- **WHEN** a normal viewport capture is requested and exactly one visible Scene Viewer exists
- **THEN** a completed PNG is published in the operating-system temporary capture area
- **AND** the user's active viewer remains usable after capture

#### Scenario: Several Scene Viewers are available without a pane selector
- **WHEN** viewport capture is requested without a pane name and more than one visible Scene Viewer exists
- **THEN** Capture fails with `scene_viewer_ambiguous`
- **AND** `context.panes` contains the same pane catalog fields as viewport inspection
- **AND** Capture does not choose a Scene Viewer by enumeration order

#### Scenario: Explicit pane does not exist
- **WHEN** viewport capture names a Scene Viewer pane tab that is not visible
- **THEN** Capture fails with `scene_viewer_not_found`
- **AND** `context.panes` contains the available Scene Viewer catalog

#### Scenario: Explicit pane name is duplicated
- **WHEN** more than one visible Scene Viewer has the explicitly requested pane-tab name
- **THEN** Capture fails with `scene_viewer_ambiguous`
- **AND** does not choose either matching pane

### Requirement: Capture directed views without modifying the user's viewer

Directed captures SHALL use a temporary/cloned Scene Viewer state rather than permanently changing the user's current viewer. Supported directed views SHALL be `top`, `bottom`, `front`, `back`, `left`, `right`, `persp`, and `uv`.

After changing the temporary viewport to each requested directed view, Capture SHALL frame all currently displayed geometry/objects with Houdini's viewport framing operation before capturing. No additional public padding control SHALL be applied. A capture without an explicit or preset view SHALL preserve the source viewport composition and SHALL NOT perform this directed-view reframing step.

#### Scenario: Capture a front view
- **WHEN** a front-directed capture is requested
- **THEN** the temporary capture viewer is aligned to the requested direction
- **AND** all currently displayed geometry/objects are framed in that direction before capture
- **AND** the user's original viewer orientation is not changed

#### Scenario: Capture several explicit views
- **WHEN** multiple directed views are requested
- **THEN** each requested view is captured independently
- **AND** completion of one view does not mutate the user's live Scene Viewer state for the next

### Requirement: Composite flipbook captures over the Scene Viewer background

Viewport PNGs and turntable source frames produced through the Scene Viewer flipbook path SHALL composite the captured RGBA image over the current viewport color scheme before scaling and saving. The background SHALL use a vertical gradient from Houdini's `BackgroundColor` at the top to `BackgroundBottomColor` at the bottom. The resulting PNG SHALL be fully opaque so alpha-bearing viewport elements such as the grid retain their intended appearance against the Scene Viewer background. Window capture SHALL NOT use this flipbook background-compositing path.

#### Scenario: Viewport flipbook contains transparent background pixels
- **WHEN** Houdini produces a viewport flipbook PNG with transparent or partially transparent pixels
- **THEN** Capture composites those pixels over the viewport's current top-to-bottom background gradient
- **AND** saves an opaque viewport PNG

#### Scenario: Turntable frame contains transparent background pixels
- **WHEN** Houdini produces a turntable source frame through the shared flipbook path
- **THEN** the same viewport background compositing is applied before the frame is scaled and encoded

### Requirement: Parse screenshot presets strictly

Screenshot presets SHALL be JSON objects parsed through one Capture preset loader. The loader SHALL accept only the keys and values defined by the Capture command contract and SHALL reject unknown settings rather than ignoring them. View and shading values SHALL use their source-defined case-insensitive normalization; overlay keys and attribute classes SHALL remain restricted to their defined names.

Viewport display settings SHALL be applied to a temporary cloned Scene Viewer. Attribute entries SHALL use Houdini viewport marker visualizers for the requested point/primitive/vertex/detail attributes.

#### Scenario: Inspect geometry with a preset
- **WHEN** a preset enables `smoothwire`, point numbers, and a point attribute marker
- **THEN** those settings are applied to the temporary capture viewer
- **AND** the user's original viewer remains unchanged

#### Scenario: Preset contains an unknown setting
- **WHEN** preset parsing encounters an unsupported key or value
- **THEN** Capture rejects the preset as invalid

### Requirement: Enforce mode-specific preset capabilities

Viewport capture SHALL allow preset `view`, `shading`, `overlays`, and `attributes` but not `crop`. Window capture SHALL allow only `crop`. Turntable capture SHALL allow `shading`, `overlays`, and `attributes` but not `view` or `crop`.

#### Scenario: Viewport receives a crop preset
- **WHEN** viewport capture receives a preset with `crop`
- **THEN** Capture rejects it with the viewport/window crop conflict

#### Scenario: Window receives display settings
- **WHEN** window capture receives preset shading, overlays, attributes, or view
- **THEN** Capture rejects the preset before capture

#### Scenario: Turntable receives view or crop
- **WHEN** turntable capture receives preset `view` or `crop`
- **THEN** Capture rejects the preset before frame production

### Requirement: Scale before enforcing maximum dimensions

Viewport images, window images, and turntable source frames SHALL use one shared scale-and-clamp calculation. The requested positive scale SHALL be applied first, then the result SHALL be downscaled if necessary to fit both effective `[screenshot].max_width` and `[screenshot].max_height` while preserving aspect ratio.

Generated defaults SHALL be `max_width = 2048` and `max_height = 2048`.

The common calculation SHALL be equivalent to:

```text
scaled_width  = max(1, round(source_width  * scale))
scaled_height = max(1, round(source_height * scale))
clamp = min(1.0, max_width / scaled_width, max_height / scaled_height)
final_width  = max(1, round(scaled_width  * clamp))
final_height = max(1, round(scaled_height * clamp))
```

#### Scenario: Requested scale exceeds image budget
- **WHEN** scale would produce an image larger than configured maximum dimensions
- **THEN** Capture computes the scaled size first
- **AND** reduces it to fit both configured maximum dimensions without stretching aspect ratio

#### Scenario: Scale remains within image budget
- **WHEN** the scaled dimensions are within both maximums
- **THEN** Capture does not downscale merely to reach the configured maximum

### Requirement: Capture the Houdini main window

Capture SHALL be able to capture the Houdini main application window through the supported operating-system/window capture path.

#### Scenario: Capture the main UI
- **WHEN** a window capture is requested without a crop selector
- **THEN** the published PNG represents the Houdini main window

### Requirement: Return image-relative UI bounds as structured result data

Window capture SHALL collect pane-tab and Scene Viewer viewport bounds and transform them into coordinates relative to the final published image, accounting for native window coordinates, DPI conversion, crop, scale, and maximum-dimension clamping. The resulting bounds document SHALL be returned as structured command data.

#### Scenario: Window screenshot is resized
- **WHEN** a captured window image is resized before publication
- **THEN** returned bounds describe locations in the final image coordinate space
- **AND** returned width/height equal the final PNG dimensions

### Requirement: Crop a window capture to one supported UI region

Window capture SHALL support selecting one pane tab such as a Network Editor or one Scene Viewer viewport when the selector resolves unambiguously. Pane tabs MAY be selected by pane-tab name or pane type; repeated matches MAY use a zero-based `:N` suffix. Nested Scene Viewer viewports SHALL use `viewport:<type-or-name>` and MAY also use a zero-based `:N` suffix. Ambiguous, missing, or out-of-range selectors SHALL fail rather than selecting an arbitrary region.

Cropping SHALL occur before final scale-and-clamp so the selected region receives the available output resolution.

#### Scenario: Crop a Network Editor
- **WHEN** the crop selector resolves to one Network Editor pane tab
- **THEN** the final image is cropped to that pane's image-relative bounds before final resize

#### Scenario: Crop a Scene Viewer viewport
- **WHEN** the crop selector resolves to one viewport
- **THEN** the final image is cropped to that viewport's bounds

#### Scenario: Crop selector is ambiguous
- **WHEN** more than one visible region satisfies the selector
- **THEN** Capture reports ambiguity and does not guess

### Requirement: Use operating-system temporary storage

Screenshot PNGs and turntable videos SHALL be published through the shared temporary-artifact boundary below the operating-system temporary directory and returned as filesystem paths according to the Capture command contracts. Capture SHALL provide the already-known output extension (`.png` or `.mp4`) and SHALL NOT MIME-sniff its own encoded output.

#### Scenario: Screenshot succeeds
- **WHEN** a PNG is published
- **THEN** its default capture location is in the operating-system temporary area

#### Scenario: Turntable succeeds
- **WHEN** a video is encoded successfully
- **THEN** the returned MP4 path is in the managed temporary capture area

### Requirement: Use readable sequential capture names

Screenshot filenames SHALL use the readable `kind + minute + sequence` convention so multiple captures are easy to distinguish without opaque random names. Turntable working/output locations SHALL likewise avoid collisions for captures in the same minute.

#### Scenario: Multiple viewport captures occur in one minute
- **WHEN** more than one viewport capture is published during the same minute
- **THEN** each receives a distinct monotonically sequenced filename for that kind/minute

### Requirement: Publish only completed capture files

Capture SHALL use the shared temporary-artifact publication boundary so partially written PNGs or MP4 files are never exposed as successful output. Temporary/in-progress files SHALL be finalized or otherwise withheld until complete.

#### Scenario: Capture fails during image production
- **WHEN** the capture pipeline fails before a valid PNG is complete
- **THEN** no incomplete final PNG is advertised as successful

#### Scenario: Video encoding fails
- **WHEN** `ffmpeg` fails before a valid MP4 is complete
- **THEN** no successful turntable video path is returned

### Requirement: Expire temporary capture output lazily

Capture SHALL lazily remove expired Houbridge-created screenshot and turntable output according to configured retention. Cleanup SHALL target Houbridge's known temporary naming/layout and SHALL not delete output that the user copied or moved elsewhere.

#### Scenario: A capture command runs
- **WHEN** Capture starts a new managed capture operation
- **THEN** expired Houbridge capture files in the managed temporary area may be reclaimed

#### Scenario: A capture was moved elsewhere
- **WHEN** prior output no longer resides in the managed temporary capture location
- **THEN** cleanup does not chase and delete the moved copy

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

### Requirement: Capture a clockwise turntable and encode video

Turntable capture SHALL clone the current Scene Viewer, choose an available Perspective viewport, preserve its current camera position as the starting position, and orbit that camera clockwise through 360 degrees around the explicit world-space pivot on world Y. The pivot SHALL default to `(0,0,0)`. Every frame SHALL remain aimed at that pivot. The user's Scene Viewer SHALL not be modified.

The default frame count SHALL be `160`; the default FPS SHALL be `30`.

#### Scenario: Capture the default turntable
- **WHEN** no explicit pivot, frame count, or FPS is supplied
- **THEN** Capture produces 160 source frames around world origin
- **AND** the frames are encoded at 30 FPS
- **AND** the user's current Scene Viewer is not modified

#### Scenario: Capture around an explicit pivot
- **WHEN** the caller supplies three finite world-space coordinates
- **THEN** those coordinates are used as the turntable pivot
- **AND** every frame remains aimed at that pivot

#### Scenario: Reject an invalid pivot
- **WHEN** the pivot does not contain exactly three finite numbers
- **THEN** Capture rejects the request before frame capture

### Requirement: Treat turntable frames as encoding intermediates

Turntable capture SHALL support MP4 video as its only published artifact. Sequential PNG source frames MAY be generated in transient storage for encoding but SHALL NOT be retained as supported output after successful encoding and SHALL NOT be part of the public success contract.

#### Scenario: Video encoding succeeds
- **WHEN** all requested turntable frames are captured and encoding succeeds
- **THEN** the command publishes the MP4 video artifact
- **AND** transient source frames are not retained as supported output artifacts
- **AND** public success does not expose frame directory, frame pattern, or frame count fields

### Requirement: Always encode turntable video with ffmpeg

Turntable capture SHALL invoke `ffmpeg` after source-frame capture. The encode profile SHALL use H.264 (`libx264`) with `yuv420p`. Odd frame dimensions SHALL be padded to codec-safe even dimensions without changing the source aspect content. If `ffmpeg` is unavailable or encoding fails, turntable capture SHALL fail rather than returning a frame-sequence success result.

#### Scenario: ffmpeg is unavailable
- **WHEN** `ffmpeg` cannot be resolved on `PATH`
- **THEN** Capture reports `ffmpeg_not_found`
- **AND** no successful turntable result is emitted

#### Scenario: Accepted frame dimensions are odd
- **WHEN** an encoded source frame has odd width or height
- **THEN** the encoding filter pads it to the next even dimension

### Requirement: Keep injected Capture code under the Capture script boundary

Houdini-side viewport/window/turntable implementation SHALL be grouped below `houbridge/houdini/scripts/capture/`, with common display/view/sizing/preset helpers factored there rather than duplicated as large host-side source strings.

#### Scenario: Screenshot and turntable share viewer helpers
- **WHEN** both features need cloning, sizing, presets, or display logic
- **THEN** shared injected helpers live in focused Capture script modules
- **AND** host-side Capture services remain orchestration-focused
