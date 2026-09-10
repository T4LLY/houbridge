# Houbridge Skill Specification

## Purpose

Define mandatory authoring rules that the Houbridge Skill follows when it creates reusable local Python scripts for Houbridge.

## Requirements

### Requirement: Give every newly created workspace script a module description

When the Houbridge Skill creates a new Python file below `.houbridge/python`, the file SHALL contain a non-empty Python module docstring that describes the script's intended purpose. The docstring SHALL be a valid module docstring discoverable through Python AST parsing and SHALL be the script description consumed by `houbridge search script`.

The Skill SHALL NOT create a sidecar JSON/YAML/TOML metadata file, custom description comment syntax, or a separate description database for this purpose.

#### Scenario: Skill creates a reusable script
- **WHEN** the Houbridge Skill creates `.houbridge/python/build.py`
- **THEN** `build.py` contains a non-empty module docstring describing what the script is intended to do
- **AND** Local Script Search can expose that docstring as the script description

#### Scenario: Description metadata is represented once
- **WHEN** the Skill writes the description for a newly created workspace script
- **THEN** the module docstring is the authoritative representation
- **AND** no parallel sidecar description metadata is required

### Requirement: Preserve compatibility with existing workspace scripts

The Skill authoring requirement SHALL NOT make a module docstring a runtime prerequisite for arbitrary existing or user-authored files below `.houbridge/python`. Search and execution SHALL continue to accept such scripts when they otherwise satisfy their respective command contracts.

#### Scenario: Existing script has no module docstring
- **WHEN** an existing user-authored workspace script lacks a module docstring
- **THEN** Local Script Search may return the script without a `description` field
- **AND** the missing description alone does not make the script invalid
