# HIP Command Specification

## Purpose

Define the public syntax and JSON response contract for inspecting and saving the current HIP file.

## Requirements

### Requirement: Expose HIP info

The syntax SHALL be:

```text
houbridge hip info [--session INTEGER]
```

`--session` SHALL follow the shared registered-session selection rule. Success SHALL return exactly:

```json
{"path":"C:/project/scene.hip","dirty":true,"new":false}
```

`path` SHALL be the absolute path returned by `hou.hipFile.path()`. `dirty` SHALL be the value returned by `hou.hipFile.hasUnsavedChanges()`. `new` SHALL be the value returned by `hou.hipFile.isNewFile()`.

#### Scenario: Inspect a selected session
- **WHEN** `houbridge hip info --session 3` is invoked
- **THEN** session `3` is resolved through the normal live Session boundary
- **AND** the command returns the current HIP state through the common Output subsystem

### Requirement: Expose HIP save

The syntax SHALL be:

```text
houbridge hip save [--session INTEGER]
```

No file path, Save As, backup, increment, autosave, or load option SHALL be exposed. Success SHALL return the current HIP path plus whether a native save was performed:

```json
{"path":"C:/project/scene.hip","status":"saved"}
```

`status` SHALL be `saved` when `hou.hipFile.save()` was called successfully and `unchanged` when the existing HIP had no unsaved changes and the native save was skipped.

#### Scenario: Save the primary session
- **WHEN** `houbridge hip save` is invoked without `--session`
- **THEN** the current primary registered session is resolved
- **AND** its existing HIP file is saved only when Houdini reports unsaved changes
- **AND** the HIP path plus `status: "saved"` or `status: "unchanged"` is returned through the common Output subsystem

#### Scenario: Current file has no established save target
- **WHEN** `houbridge hip save` targets a scene for which `hou.hipFile.isNewFile()` is true
- **THEN** the command fails through the common BridgeError envelope with code `hip_save_target_missing`
- **AND** no implicit Save As is performed
