## MODIFIED Requirements

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
| `--preset PATH` | Existing readable screenshot-preset JSON file; non-beauty passes accept only preset `view`. |
| `--pane TEXT` | Exact Scene Viewer pane-tab name to capture from. |
| `--pass TEXT` | `beauty`, `depth`, `grid`, `normal`, `object-id`, or `curvature`; default `beauty`. |
| `--model PATH` | Repeatable absolute OBJ node path; valid only for non-beauty passes and filters rendered analysis geometry. |
| `--unit FLOAT` | Required only for `--pass grid`; finite and greater than zero. |
| `--curvature-scale FLOAT` | Curvature-only response multiplier; effective default `1.0`; finite and greater than zero. |
| `--curvature-colormap TEXT` | Curvature-only colormap `gray` or `rg`; effective default `rg`. |
| `--session INTEGER` | Positive registered session number; uses primary when omitted. |

`--info` SHALL NOT be combined with capture directions, non-default `--scale`, `--preset`, `--pane`, a non-beauty `--pass`, `--model`, `--unit`, or explicit curvature options.

When no individual view is supplied, a preset view SHALL be used when defined; otherwise the active viewport SHALL be captured. Explicit direction flags take precedence over a preset `view`.

When `--pane` is omitted, capture SHALL proceed automatically only when exactly one visible Scene Viewer pane exists. If several are visible, capture SHALL fail with `scene_viewer_ambiguous`. When `--pane` is supplied, its value SHALL match exactly one visible Scene Viewer pane-tab name. No match SHALL fail with `scene_viewer_not_found`; multiple exact matches SHALL fail with `scene_viewer_ambiguous`. These selection failures SHALL include the available Scene Viewer catalog under `context.panes`, using the same pane entry schema as `--info`.

Every explicit direction and every effective preset `view` SHALL change the temporary capture viewport to that view and frame all currently displayed geometry/objects before capture. Capture with neither an explicit direction nor a preset `view` SHALL preserve the source viewport composition. `--model` SHALL filter only non-beauty rendering and SHALL NOT change these framing/composition rules.

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

#### Scenario: Request one analysis capture
- **WHEN** `houbridge capture viewport --pass normal` produces one image
- **THEN** the public result keeps the same single-image schema:

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

#### Scenario: Request multiple directional analysis captures
- **WHEN** `houbridge capture viewport --front --right --pass depth` produces multiple images
- **THEN** the public result keeps the same `captures` schema and view labels as Beauty capture

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

#### Scenario: Model filtering does not change directed framing
- **WHEN** a directed non-beauty viewport capture supplies one or more `--model` values
- **THEN** the temporary viewport still frames all currently displayed geometry/objects using the existing directed-view rule
- **AND** only the selected displayed objects contribute to the analysis rendering

### Requirement: Expose camera discovery, detail, and capture through one command

The syntax SHALL be:

```text
houbridge capture camera [CAMERA_PATH] [OPTIONS]
```

Supported options SHALL be:

| Option | Constraint / meaning |
| --- | --- |
| `--list` | List initially supported cameras without capturing; CAMERA_PATH SHALL be omitted. |
| `--detail` | Return bounded detail for CAMERA_PATH without capturing. |
| `--scale FLOAT` | Camera capture only; greater than zero, default `1.0`; camera resolution is scaled before shared screenshot maximums are enforced. |
| `--pane TEXT` | Camera capture only; exact Scene Viewer pane-tab name to use as the display/capture source. |
| `--pass TEXT` | Camera capture only; `beauty`, `depth`, `grid`, `normal`, `object-id`, or `curvature`; default `beauty`. |
| `--model PATH` | Camera capture only; repeatable absolute OBJ node path, valid only for non-beauty passes. |
| `--unit FLOAT` | Camera capture only; required only for `--pass grid`; finite and greater than zero. |
| `--curvature-scale FLOAT` | Camera capture only; curvature response multiplier; effective default `1.0`; finite and greater than zero. |
| `--curvature-colormap TEXT` | Camera capture only; curvature colormap `gray` or `rg`; effective default `rg`. |
| `--session INTEGER` | Positive registered session number; uses primary when omitted. |

`CAMERA_PATH` SHALL be required unless `--list` is supplied. `--list` SHALL NOT be combined with CAMERA_PATH, `--detail`, non-default `--scale`, `--pane`, a non-beauty `--pass`, `--model`, `--unit`, or explicit curvature options; those combinations SHALL fail with `capture_camera_list_conflict`. `--detail` SHALL require CAMERA_PATH and SHALL NOT be combined with non-default `--scale`, `--pane`, a non-beauty `--pass`, `--model`, `--unit`, or explicit curvature options; those combinations SHALL fail with `capture_camera_detail_conflict`. A missing CAMERA_PATH outside list mode SHALL fail with `camera_path_required` through the normal handled-error output path.

Initial discovery SHALL include only standard OBJ Camera instances and standard Camera SOP instances that currently produce camera primitives on their first output. It SHALL emit exactly `path`, `type`, and `resolution` for each camera, with `type` exactly `obj` or `sop`, sorted by `path`. SOP list paths SHALL include a primitive-number selector so each emitted path can be passed directly to camera capture. COP, LOP/USD, and APEX cameras are planned future camera types and SHALL be excluded until their capture support is implemented.

A successful list SHALL have the shape:

```json
{
  "cameras":[
    {"path":"/obj/cam1","type":"obj","resolution":[1920,1080]},
    {"path":"/obj/geo1/camera1:0","type":"sop","resolution":[1280,720]}
  ]
}
```

`--detail` SHALL inspect only the named camera and SHALL return exactly `path`, `type`, `resolution`, `projection`, `focal_length`, `aperture`, `pixel_aspect`, `near_clip`, `far_clip`, `focus_distance`, and `f_stop`. It SHALL NOT dump arbitrary camera metadata or renderer-specific parameters.

A successful detail result SHALL have the shape:

```json
{
  "path":"/obj/cam1",
  "type":"obj",
  "resolution":[1920,1080],
  "projection":"perspective",
  "focal_length":50.0,
  "aperture":41.4214,
  "pixel_aspect":1.0,
  "near_clip":0.1,
  "far_clip":1000.0,
  "focus_distance":5.0,
  "f_stop":5.6
}
```

Camera capture SHALL use the same Scene Viewer pane-selection semantics and structured pane errors as viewport and turntable capture. It SHALL preserve camera framing, use the camera's own resolution as the source dimensions, apply `--scale` and the shared screenshot maximums, and emit exactly:

```json
{"path":"D:/Temp/.../camera20260928-1145-001.png"}
```

Non-beauty camera capture SHALL use the same source camera framing, source resolution, scale/clamp rule, pane-selection behavior, and success JSON shape as Beauty camera capture. `--model` SHALL filter only analysis geometry and SHALL NOT reframe the camera.

An explicit camera path SHALL be absolute. Initial explicit support SHALL accept standard OBJ Camera paths and standard Camera SOP first-output paths. A Camera SOP path MAY omit its selector only when exactly one camera primitive is present; otherwise it SHALL fail with `camera_ambiguous`. A missing camera or primitive SHALL fail with `camera_not_found`, a Camera SOP that produces no camera primitive or an OBJ Camera path with a primitive selector SHALL fail with `camera_invalid`, and node types outside the initial support set SHALL fail with `camera_unsupported`.

#### Scenario: List cameras for path discovery
- **WHEN** `houbridge capture camera --list` is invoked
- **THEN** only lightweight supported camera entries are returned
- **AND** no Scene Viewer pane is required

#### Scenario: Inspect one camera in detail
- **WHEN** `houbridge capture camera /obj/cam1 --detail` is invoked
- **THEN** only that camera's bounded detail schema is returned
- **AND** no image is captured

#### Scenario: Capture one camera
- **WHEN** `houbridge capture camera /obj/cam1 --scale 0.5` is invoked
- **THEN** the source dimensions are the camera resolution
- **AND** the published PNG uses the scaled/clamped dimensions
- **AND** camera composition is not reframed

#### Scenario: Capture one camera analysis pass
- **WHEN** `houbridge capture camera /obj/cam1 --pass normal --scale 0.5` is invoked
- **THEN** the source dimensions are the camera resolution
- **AND** the published PNG uses the same scaled/clamped dimension rule as Beauty capture
- **AND** camera composition is not reframed
- **AND** output retains the single `path` success schema

#### Scenario: Camera path is omitted outside list mode
- **WHEN** `houbridge capture camera` or `houbridge capture camera --detail` is invoked without CAMERA_PATH
- **THEN** the command fails with `camera_path_required`

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

A Beauty viewport preset MAY use `view`, `shading`, `overlays`, and `attributes`, but SHALL NOT use `crop`; a crop in viewport mode SHALL fail with `screenshot_crop_requires_window`. A non-beauty viewport preset MAY use only `view`; `shading`, `overlays`, or `attributes` with a non-beauty pass SHALL fail with `capture_analysis_preset_invalid`, and `crop` remains invalid under the existing viewport/window crop rule. A window preset MAY use only `crop`; display/view settings in window mode SHALL fail with `screenshot_window_preset_invalid`. A turntable preset MAY use `shading`, `overlays`, and `attributes`, but SHALL NOT use `view` or `crop`; those keys in turntable mode SHALL fail with `turntable_preset_invalid`.

Example viewport preset:

```json
{
  "view":"uv",
  "shading":"smoothwire",
  "overlays":{"point_numbers":true},
  "attributes":[{"class":"point","name":"P"}]
}
```

Example analysis viewport preset:

```json
{"view":"front"}
```

Example window preset:

```json
{"crop":"network_editor"}
```

#### Scenario: Explicit viewport direction overrides preset view
- **WHEN** a preset contains `{"view":"uv"}` and `--front` is supplied
- **THEN** the front view is captured
- **AND** other compatible preset display settings still apply

#### Scenario: Analysis preset supplies only view
- **WHEN** a non-beauty viewport capture receives a preset containing only `view`
- **THEN** that view participates in the existing viewport view-selection rules

#### Scenario: Analysis preset contains Beauty display settings
- **WHEN** a non-beauty viewport capture receives preset `shading`, `overlays`, or `attributes`
- **THEN** capture fails with `capture_analysis_preset_invalid`
- **AND** those settings are not silently ignored

#### Scenario: Explicit window crop overrides preset crop
- **WHEN** a window preset contains one `crop` and `--crop` supplies another
- **THEN** the explicit `--crop` selector is used

#### Scenario: Preset contains an unsupported overlay
- **WHEN** `overlays` contains a key outside the supported set
- **THEN** the preset is rejected rather than silently ignoring that key

## ADDED Requirements

### Requirement: Expose one shared analysis-pass option contract on viewport and camera capture

`capture viewport` and camera capture mode SHALL accept one common analysis-pass contract. `capture window`, camera `--list`, camera `--detail`, and `capture turntable` SHALL NOT gain analysis-pass behavior in this change.

`--pass` SHALL accept exactly `beauty`, `depth`, `grid`, `normal`, `object-id`, and `curvature`, with `beauty` as the effective default. An unsupported value SHALL fail through the handled-error path with `invalid_capture_pass` rather than selecting a fallback pass.

`--model PATH` SHALL be repeatable and each supplied value SHALL be an absolute OBJ node path. It SHALL be valid only with non-beauty passes. A missing path SHALL fail with `capture_model_not_found`; an existing path that is not an eligible OBJ object path SHALL fail with `capture_model_invalid`. Omitting `--model` SHALL mean all currently displayed geometry is eligible for the analysis pass.

`grid` SHALL require `--unit FLOAT`. A missing grid unit SHALL fail with `grid_unit_required`; a non-finite or non-positive grid unit SHALL fail with `invalid_grid_unit`. Supplying `--unit` to any other pass SHALL fail with `capture_pass_option_conflict`.

`curvature` SHALL use effective defaults `--curvature-scale 1.0` and `--curvature-colormap rg`. An explicit scale SHALL be finite and greater than zero or fail with `invalid_curvature_scale`. An explicit colormap SHALL be exactly `gray` or `rg` or fail with `invalid_curvature_colormap`. Explicit curvature options on a non-curvature pass SHALL fail with `capture_pass_option_conflict`.

`--model` on Beauty capture SHALL fail with `capture_pass_option_conflict` so Beauty remains the existing unfiltered capture path.

Handled semantic failures SHALL use the existing common error envelope. For example, a grid option on the wrong pass SHALL be shaped like:

```json
{"error":true,"code":"capture_pass_option_conflict","message":"--unit is only valid with --pass grid."}
```

A missing model SHALL be shaped like:

```json
{"error":true,"code":"capture_model_not_found","message":"Model node was not found: /obj/missing"}
```

Successful analysis capture SHALL not add pass/model metadata to the existing success JSON schemas.

#### Scenario: Beauty remains the default
- **WHEN** viewport or camera capture is invoked without `--pass`
- **THEN** the effective pass is `beauty`
- **AND** no analysis renderer is selected

#### Scenario: Grid requires a positive finite unit
- **WHEN** `--pass grid` is supplied without `--unit`
- **THEN** capture fails with `grid_unit_required`
- **WHEN** the supplied grid unit is zero, negative, NaN, or infinite
- **THEN** capture fails with `invalid_grid_unit`

#### Scenario: Curvature defaults are applied only to curvature
- **WHEN** `--pass curvature` is supplied without explicit curvature options
- **THEN** effective scale is `1.0`
- **AND** effective colormap is `rg`

#### Scenario: Pass-specific option is supplied to another pass
- **WHEN** a caller supplies `--unit` outside Grid or explicitly supplies curvature options outside Curvature
- **THEN** capture fails with `capture_pass_option_conflict`

#### Scenario: Model filter is omitted
- **WHEN** a non-beauty viewport or camera capture has no `--model`
- **THEN** all currently displayed geometry is eligible to contribute to the analysis image

#### Scenario: Model filter is repeated
- **WHEN** one or more valid `--model` options are supplied to a non-beauty pass
- **THEN** only currently displayed geometry owned by those exact OBJ objects is eligible to contribute

#### Scenario: Turntable has no analysis-pass CLI yet
- **WHEN** this change is implemented
- **THEN** the documented `capture turntable` option set remains unchanged
- **AND** turntable analysis passes require a later specification change
