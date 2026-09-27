# Capture Command Specification

## Purpose

Define the public syntax, options, validation rules, preset format, image bounds, and JSON response contracts for shared Scene Viewer pane discovery, viewport/window capture, OCR, and turntable video capture.

## Requirements

### Requirement: Expose shared Scene Viewer pane discovery

The syntax SHALL be:

```text
houbridge capture panes [--session INTEGER]
```

`--session INTEGER` SHALL be a positive registered session number and SHALL use the primary session when omitted.

The command SHALL return one `panes` array using the same Scene Viewer catalog service and public schema as `houbridge capture viewport --info`. Each pane SHALL contain exactly `name`, `current_node`, and `viewports`; each viewport SHALL contain exactly `name`, `type`, `width`, and `height`. `current_node` SHALL be a node path string or `null`. Pane ordering SHALL have no selection or priority semantics.

#### Scenario: Request capture pane discovery
- **WHEN** `houbridge capture panes` is invoked
- **THEN** output contains one entry per visible Scene Viewer pane tab
- **AND** the result schema is identical to viewport `--info`

#### Scenario: Request pane discovery from a selected session
- **WHEN** `houbridge capture panes --session 3` is invoked
- **THEN** discovery targets registered session `3`

#### Scenario: No Scene Viewer is available
- **WHEN** no visible Scene Viewer pane is available
- **THEN** the command fails with the same structured missing-viewer failure as viewport `--info`

### Requirement: Expose viewport capture and viewport info through one command

The syntax SHALL be:

```text
houbridge capture viewport [OPTIONS]
```

Supported options SHALL be:

| Option | Constraint / meaning |
| --- | --- |
| `--info` | Return the same shared Scene Viewer pane catalog as `houbridge capture panes` instead of capturing. |
| `--top` | Capture top view. |
| `--bottom` | Capture bottom view. |
| `--front` | Capture front view. |
| `--back` | Capture back view. |
| `--left` | Capture left view. |
| `--right` | Capture right view. |
| `--persp` | Capture perspective view. |
| `--uv` | Capture UV view. |
| `--scale FLOAT` | Must be greater than zero; default `1.0`; final dimensions are constrained by the shared screenshot maximums. |
| `--preset PATH` | Existing readable screenshot-preset JSON file. |
| `--pane TEXT` | Exact Scene Viewer pane-tab name to capture from. |
| `--session INTEGER` | Positive registered session number; uses primary when omitted. |

`--info` SHALL NOT be combined with capture directions, non-default `--scale`, `--preset`, or `--pane`.

When no individual view is supplied, a preset view SHALL be used when defined; otherwise the active viewport SHALL be captured. Explicit direction flags take precedence over a preset `view`.

When `--pane` is omitted, capture SHALL proceed automatically only when exactly one visible Scene Viewer pane exists. If several are visible, capture SHALL fail with `scene_viewer_ambiguous`. When `--pane` is supplied, its value SHALL match exactly one visible Scene Viewer pane-tab name. No match SHALL fail with `scene_viewer_not_found`; multiple exact matches SHALL fail with `scene_viewer_ambiguous`. These selection failures SHALL include the available Scene Viewer catalog under `context.panes`, using the same pane entry schema as `--info`.

Every explicit direction and every effective preset `view` SHALL change the temporary capture viewport to that view and frame all currently displayed geometry/objects before capture. Capture with neither an explicit direction nor a preset `view` SHALL preserve the source viewport composition.

#### Scenario: Request viewport info through the compatibility entry point
- **WHEN** `--info` is used alone
- **THEN** output is identical in schema and discovery semantics to `houbridge capture panes`
- **AND** output contains a `panes` array with one entry per visible Scene Viewer pane tab
- **AND** each pane contains exactly `name`, `current_node`, and `viewports`
- **AND** `current_node` is a node path string or `null`
- **AND** `viewports` contains every viewport currently visible in that Scene Viewer
- **AND** each viewport contains exactly `name`, `type`, `width`, and `height`
- **AND** pane ordering has no selection or priority semantics
- **AND** output is shaped like:

```json
{
  "panes": [
    {
      "name":"panetab1",
      "current_node":"/obj/robot/OUT",
      "viewports":[
        {"name":"persp1","type":"persp","width":1280,"height":720}
      ]
    },
    {
      "name":"panetab4",
      "current_node":null,
      "viewports":[]
    }
  ]
}
```

#### Scenario: Request one capture
- **WHEN** exactly one image is produced
- **THEN** output is:

```json
{"path":"D:/Temp/.../viewport20260908-2100-001.png"}
```

#### Scenario: Request multiple directional captures
- **WHEN** multiple image paths are produced
- **THEN** output is:

```json
{
  "captures": [
    {"view":"front","path":"..."},
    {"view":"right","path":"..."}
  ]
}
```

#### Scenario: Info conflicts with capture options
- **WHEN** `--info` is combined with a capture option
- **THEN** the command fails with `capture_info_conflict`

#### Scenario: Multiple panes require an explicit selector
- **WHEN** capture is requested without `--pane` and multiple visible Scene Viewer panes exist
- **THEN** the command fails with `scene_viewer_ambiguous`
- **AND** `context.panes` contains the available Scene Viewer catalog

#### Scenario: Explicit pane is missing
- **WHEN** `--pane` does not match any visible Scene Viewer pane-tab name
- **THEN** the command fails with `scene_viewer_not_found`
- **AND** `context.panes` contains the available Scene Viewer catalog

#### Scenario: Directed view is reframed
- **WHEN** a direction flag or preset `view` selects a directed capture
- **THEN** the temporary viewport frames all currently displayed geometry/objects after changing view type and before capture

### Requirement: Define the screenshot preset JSON contract

`--preset PATH` SHALL load one JSON object. The only permitted top-level keys SHALL be `view`, `shading`, `overlays`, `attributes`, and `crop`. An invalid preset root, unknown top-level key, invalid shading/overlay/attribute/crop value, or malformed preset structure SHALL fail with `invalid_screenshot_preset`. An invalid `view` value SHALL fail with `invalid_screenshot_view`, matching the shared view validator.

`view`, when present, SHALL be matched case-insensitively, normalized to lowercase, and SHALL be one of:

```text
top bottom front back left right persp uv
```

`shading`, when present, SHALL be matched case-insensitively, normalized to lowercase, and SHALL be one of:

```text
wire wireghost hiddenline hiddenlineghost flat flatwire smooth smoothwire matcap matcapwire
```

`overlays` SHALL be an object whose values are booleans and whose keys are limited exactly to:

```text
point_markers point_numbers point_normals point_uvs point_positions
prim_numbers prim_normals
vertex_markers vertex_numbers vertex_normals vertex_uvs
uv_backfaces uv_overlap
```

`attributes` SHALL be an array. Each element SHALL contain exactly `class` and `name`. `class` SHALL be exactly one of `point`, `prim`, `vertex`, or `detail`, and `name` SHALL be a non-empty string after surrounding whitespace is removed.

`crop`, when present, SHALL be a non-empty string after surrounding whitespace is removed.

A viewport preset MAY use `view`, `shading`, `overlays`, and `attributes`, but SHALL NOT use `crop`; a crop in viewport mode SHALL fail with `screenshot_crop_requires_window`. A window preset MAY use only `crop`; display/view settings in window mode SHALL fail with `screenshot_window_preset_invalid`. A turntable preset MAY use `shading`, `overlays`, and `attributes`, but SHALL NOT use `view` or `crop`; those keys in turntable mode SHALL fail with `turntable_preset_invalid`.

Example viewport preset:

```json
{
  "view":"uv",
  "shading":"smoothwire",
  "overlays":{"point_numbers":true},
  "attributes":[{"class":"point","name":"P"}]
}
```

Example window preset:

```json
{"crop":"network_editor"}
```

#### Scenario: Explicit viewport direction overrides preset view
- **WHEN** a preset contains `{"view":"uv"}` and `--front` is supplied
- **THEN** the front view is captured
- **AND** other compatible preset display settings still apply

#### Scenario: Explicit window crop overrides preset crop
- **WHEN** a window preset contains one `crop` and `--crop` supplies another
- **THEN** the explicit `--crop` selector is used

#### Scenario: Preset contains an unsupported overlay
- **WHEN** `overlays` contains a key outside the supported set
- **THEN** the preset is rejected rather than silently ignoring that key

### Requirement: Apply scale before shared screenshot maximum dimensions

For viewport, window, and turntable frame generation, `--scale` SHALL be applied before enforcing the effective `[screenshot].max_width` and `[screenshot].max_height`. Generated defaults SHALL be `2048` and `2048`.

For a source image of `width` by `height`, the sizing rule SHALL be equivalent to:

```text
scaled_width  = max(1, round(width  * scale))
scaled_height = max(1, round(height * scale))
clamp = min(1.0, max_width / scaled_width, max_height / scaled_height)
final_width  = max(1, round(scaled_width  * clamp))
final_height = max(1, round(scaled_height * clamp))
```

Aspect ratio SHALL be preserved. A positive `--scale` has no separate public upper bound; an oversized requested scale is reduced by the configured maximum dimensions.

For window crop, cropping SHALL occur before this scale-and-clamp step so the selected region receives the available output resolution.

#### Scenario: Scale requests more than 2048 pixels with generated defaults
- **WHEN** the scaled image would exceed either generated screenshot maximum
- **THEN** the final image is reduced to fit within `2048x2048`
- **AND** its aspect ratio is preserved

### Requirement: Expose full-window capture with inline bounds JSON

The syntax SHALL be:

```text
houbridge capture window [--scale FLOAT] [--crop TEXT] [--preset PATH] [--session INTEGER]
```

`--scale` defaults to `1.0` and SHALL be greater than zero. `--crop` is optional. `--preset` SHALL identify an existing readable screenshot-preset JSON file and SHALL obey the window-preset restrictions above.

A successful window capture SHALL emit the image path and the bounds document directly under `bounds`:

```json
{
  "path":"D:/Temp/.../window20260908-2100-001.png",
  "bounds":{
    "width":1280,
    "height":720,
    "coordinate_space":"final_png_top_left",
    "source_width":2560,
    "source_height":1440,
    "scale_x":0.5,
    "scale_y":0.5,
    "areas":[
      {
        "type":"scene_viewer",
        "name":"pane1",
        "x":0,
        "y":0,
        "width":900,
        "height":720,
        "viewports":[
          {"type":"persp","name":"persp1","x":0,"y":0,"width":900,"height":720}
        ]
      }
    ]
  }
}
```

Each area SHALL contain `type`, `name`, `x`, `y`, `width`, and `height`. Scene Viewer areas MAY additionally contain `viewports`, where each viewport contains `type`, `name`, `x`, `y`, `width`, and `height`. When crop is used, `bounds` SHALL additionally contain `cropped_from` with the effective selector.

The bounds document SHALL describe the final PNG coordinate space after DPI conversion, crop, scale, and maximum-dimension clamping.

#### Scenario: Window capture succeeds
- **WHEN** Houdini publishes a valid window PNG and bounds document
- **THEN** the command emits `path` and `bounds`
- **AND** `bounds.width` and `bounds.height` match the final PNG

### Requirement: Expose screenshot OCR

The syntax SHALL be:

```text
houbridge capture ocr IMAGE
```

`IMAGE` is a required path argument. Missing/non-file input SHALL fail with `ocr_image_not_found` after dispatch.

Normal OCR success SHALL emit:

```json
{
  "ocr": {
    "File": [
      {"score":0.99,"bbox":[1,2,100,20]}
    ]
  }
}
```

Each recognized text string is a key. Its value is an array because the same text MAY occur multiple times. Each item contains OCR `score` (`number` or `null`) and `bbox` as `[left, top, right, bottom]` integer coordinates. OCR scores are not Search scores and are not transformed by the Search score formatter.

If no OCR boxes are returned, success SHALL be:

```json
{"ocr":{}}
```

Large OCR logical output SHALL use the common Output Resource fallback rather than a capture-specific threshold implementation.

#### Scenario: OCR result exceeds common output budget
- **WHEN** the logical `ocr` object is too large for inline output
- **THEN** the complete OCR object is stored as a Resource
- **AND** the command emits the common minimal Resource fallback

### Requirement: Expose turntable video capture

The syntax SHALL be:

```text
houbridge capture turntable [OPTIONS]
```

Supported options SHALL be:

| Option | Constraint / default |
| --- | --- |
| `--frames INTEGER` | minimum `2`, default `160`. |
| `--fps INTEGER` | minimum `1`, default `30`. |
| `--scale FLOAT` | greater than zero, default `1.0`; final frame dimensions use the shared screenshot maximums. |
| `--pivot TEXT` | comma-separated world-space `x,y,z`, default `0,0,0`. |
| `--distance FLOAT` | optional finite camera distance from the pivot; when supplied it SHALL be greater than zero. |
| `--preset PATH` | existing readable screenshot-preset JSON file; turntable-compatible keys only. |
| `--session INTEGER` | Positive registered session number; uses primary when omitted. |

Turntable capture SHALL always encode the generated frames with `ffmpeg`. PNG frames are transient encoding intermediates only. After successful encoding, only the MP4 video SHALL be published; frame directories/patterns SHALL NOT be retained or exposed as supported output artifacts.

The orbit radius SHALL be the camera distance from the requested pivot. When `--distance` is omitted, Houbridge SHALL preserve the source Perspective viewport camera's existing distance from the pivot. When `--distance` is supplied, Houbridge SHALL preserve the source camera's direction from the pivot and normalize that offset to exactly the requested distance before generating the orbit. `--distance` values that are non-finite or less than or equal to zero SHALL fail with `invalid_turntable_distance`. If the source camera is located at the pivot so that an orbit direction cannot be derived, turntable capture SHALL fail rather than inventing a direction.

A successful turntable capture SHALL emit exactly:

```json
{"path":"D:/Temp/.../turntable.mp4"}
```

#### Scenario: Default turntable succeeds
- **WHEN** `houbridge capture turntable` is invoked
- **THEN** 160 capture frames are used to produce the video at 30 FPS
- **AND** success contains exactly the encoded video `path`

#### Scenario: Explicit turntable distance is used
- **WHEN** `--distance 5.0` is supplied and the source camera has a valid direction from the pivot
- **THEN** every turntable camera position SHALL remain exactly `5.0` world units from the pivot
- **AND** the starting orbit direction SHALL match the source camera direction from the pivot

#### Scenario: Turntable distance is invalid
- **WHEN** `--distance` is zero, negative, or non-finite
- **THEN** the command fails with `invalid_turntable_distance`

#### Scenario: FFmpeg is unavailable
- **WHEN** turntable capture reaches encoding and no `ffmpeg` executable is available on `PATH`
- **THEN** the command fails with `ffmpeg_not_found`
- **AND** no successful video response is emitted
