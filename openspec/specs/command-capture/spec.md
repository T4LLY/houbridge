# Capture Command Specification

## Purpose

Define the public syntax, options, validation rules, and JSON response contracts for viewport/window capture, OCR, and turntables.

## Requirements

### Requirement: Expose viewport capture and viewport info through one command

The syntax SHALL be:

```text
houbridge capture viewport [OPTIONS]
```

Supported options SHALL be:

| Option | Constraint / meaning |
| --- | --- |
| `--info` | Return visible viewport metadata instead of capturing. |
| `--top` | Capture top view. |
| `--bottom` | Capture bottom view. |
| `--front` | Capture front view. |
| `--back` | Capture back view. |
| `--left` | Capture left view. |
| `--right` | Capture right view. |
| `--persp` | Capture perspective view. |
| `--uv` | Capture UV view. |
| `--quad` | Capture quad-layout output. |
| `--scale FLOAT` | Must be greater than zero; default `1.0`. |
| `--preset PATH` | Existing readable file. |
| `--port INTEGER` | `1..65535`. |
| `--root PATH` | Common runtime option. |
| `--hcommand TEXT` | Common runtime option. |

`--info` SHALL NOT be combined with capture directions, `--quad`, non-default `--scale`, or `--preset`. `--quad` SHALL NOT be combined with individual view flags.

When no individual view and no `--quad` are supplied, a preset view SHALL be used when defined; otherwise the active viewport SHALL be captured.

#### Scenario: Request viewport info
- **WHEN** `--info` is used alone
- **THEN** output is:

```json
{
  "viewports": [
    {"name":"persp1","type":"persp","width":1280,"height":720}
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

#### Scenario: Quad conflicts with a direction
- **WHEN** `--quad` and an individual view flag are both supplied
- **THEN** the command fails with `screenshot_view_conflict`

### Requirement: Expose full-window capture

The syntax SHALL be:

```text
houbridge capture window [--scale FLOAT] [--crop TEXT] [--preset PATH] [--port INTEGER] [--root PATH] [--hcommand TEXT]
```

`--scale` defaults to `1.0` and SHALL be greater than zero. `--crop` is optional. `--preset` SHALL identify an existing readable file.

A successful window capture SHALL emit the image and bounds JSON paths:

```json
{
  "path": "D:/Temp/.../window20260908-2100-001.png",
  "bounds_path": "D:/Temp/.../window20260908-2100-001.json"
}
```

#### Scenario: Window capture succeeds
- **WHEN** Houdini publishes a valid window PNG and UI bounds document
- **THEN** both `path` and `bounds_path` are emitted

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

Each recognized text string is a key. Its value is an array because the same text MAY occur multiple times. Each item contains `score` (`number` or `null`) and `bbox` as `[left, top, right, bottom]` integer coordinates.

If no OCR boxes are returned, success SHALL be:

```json
{"ocr":{}}
```

Large OCR logical output SHALL use the common Output Resource fallback rather than a capture-specific threshold implementation.

#### Scenario: OCR result exceeds common output budget
- **WHEN** the logical `ocr` object is too large for inline output
- **THEN** the complete OCR object is stored as a Resource
- **AND** the command emits the common minimal Resource fallback

### Requirement: Expose turntable capture

The syntax SHALL be:

```text
houbridge capture turntable [OPTIONS]
```

Supported options SHALL be:

| Option | Constraint / default |
| --- | --- |
| `--frames INTEGER` | minimum `2`, default `120`. |
| `--fps INTEGER` | minimum `1`, default `30`. |
| `--scale FLOAT` | greater than zero, default `1.0`. |
| `--pivot TEXT` | comma-separated world-space `x,y,z`, default `0,0,0`. |
| `--preset PATH` | existing readable file; turntable-compatible preset content only. |
| `--ffmpeg` | encode video after frame capture. |
| `--port INTEGER` | `1..65535`. |
| `--root PATH` | common runtime option. |
| `--hcommand TEXT` | common runtime option. |

Without video encoding, success SHALL be:

```json
{
  "directory": ".../turntable...",
  "frame_pattern": ".../frame%04d.png",
  "frame_count": 120,
  "fps": 30
}
```

When video is successfully encoded, `video_path` SHALL be added:

```json
{
  "directory": ".../turntable...",
  "frame_pattern": ".../frame%04d.png",
  "frame_count": 120,
  "fps": 30,
  "video_path": ".../turntable.mp4"
}
```

#### Scenario: Turntable frames only
- **WHEN** `--ffmpeg` is not requested
- **THEN** `video_path` is omitted

#### Scenario: FFmpeg encoding succeeds
- **WHEN** `--ffmpeg` is requested and encoding succeeds
- **THEN** `video_path` is emitted
