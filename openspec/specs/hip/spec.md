# HIP File Specification

## Purpose

Define the minimal Houbridge boundary for inspecting and saving the active native Houdini scene file.

## Requirements

### Requirement: Treat the active HIP file as native Houdini state

Hip operations SHALL target the selected registered live Houdini session and SHALL use native `hou.hipFile` APIs. Houbridge SHALL NOT copy the HIP file into its own persistence, invent a session-save format, or maintain a second authoritative scene state.

#### Scenario: Inspect the active file
- **WHEN** Hip info is requested
- **THEN** Houbridge reads the current path, new-file state, and unsaved-change state from `hou.hipFile` in the selected Houdini process

### Requirement: Save only to an established current target

Hip save SHALL perform the native equivalent of File > Save by calling `hou.hipFile.save()` without a replacement path. It SHALL NOT expose Save As, backup, increment, load, clear, merge, or autosave behavior. If Houdini reports the current file as new, Houbridge SHALL refuse the save instead of implicitly creating a file at Houdini's default unsaved path.

#### Scenario: Save a dirty existing HIP file
- **WHEN** the selected Houdini process has a non-new current HIP file
- **AND** `hou.hipFile.hasUnsavedChanges()` returns true
- **AND** Hip save is requested
- **THEN** Houbridge calls `hou.hipFile.save()` without a file-name argument
- **AND** returns the current HIP path with `status` set to `saved`

#### Scenario: Save a clean existing HIP file
- **WHEN** the selected Houdini process has a non-new current HIP file
- **AND** `hou.hipFile.hasUnsavedChanges()` returns false
- **AND** Hip save is requested
- **THEN** Houbridge succeeds without calling `hou.hipFile.save()`
- **AND** returns the current HIP path with `status` set to `unchanged`

#### Scenario: Save a new unsaved scene
- **WHEN** Houdini reports `hou.hipFile.isNewFile()` as true
- **AND** Hip save is requested
- **THEN** Houbridge fails with `hip_save_target_missing`
- **AND** it does not call `hou.hipFile.save()`

### Requirement: Preserve Houdini headless state semantics

Hip info SHALL report `hou.hipFile.hasUnsavedChanges()` and `hou.hipFile.isNewFile()` as Houdini returns them. Houbridge SHALL NOT emulate GUI-only dirty/new detection in headless mode.

#### Scenario: Inspect a headless session
- **WHEN** Houdini's non-graphical runtime reports its documented fallback values for dirty or new-file state
- **THEN** Houbridge returns those values without reinterpretation
