# Houbridge Skill Specification

## Purpose

Define mandatory authoring rules that the Houbridge Skill follows when it creates reusable local Python scripts for Houbridge.

## Requirements

### Requirement: Give every newly created workspace script a module description

When the Houbridge Skill creates a new Python file below `.houbridge/python`, the file SHALL contain a non-empty Python module docstring that describes the script's intended purpose. The docstring SHALL be a valid module docstring discoverable through Python AST parsing and SHALL be the script description consumed by `houbridge search script`.

The Skill SHALL NOT create a sidecar JSON/YAML/TOML metadata file, custom description comment syntax, or a separate description database for this purpose.

#### Scenario: Skill creates a reusable candidate
- **WHEN** the Houbridge Skill creates `.houbridge/python/_candidate/build.py`
- **THEN** `build.py` contains a non-empty module docstring describing what the script is intended to do
- **AND** Local Script Search with `--all` can expose that docstring as the script description

#### Scenario: Description metadata is represented once
- **WHEN** the Skill writes the description for a newly created workspace script
- **THEN** the module docstring is the authoritative representation
- **AND** no parallel sidecar description metadata is required

### Requirement: Stage new reusable scripts before approval

When the Houbridge Skill authors a new script intended for reuse across projects, it SHALL create the script below `.houbridge/python/_candidate/`. It SHALL NOT create that new script directly in a non-underscore top-level category or promote it from `_candidate/` to such a category unless the user explicitly approves that placement. Existing approved scripts in non-underscore categories MAY be edited in place when the user requests changes.

#### Scenario: New reusable tool is authored
- **WHEN** the Skill creates a new cross-project reusable tool
- **THEN** the initial file is placed below `.houbridge/python/_candidate/`
- **AND** it is not automatically promoted into an approved category

#### Scenario: Candidate is approved
- **WHEN** the user explicitly approves promotion of a candidate
- **THEN** the Skill may move it into an appropriate non-underscore reusable category

#### Scenario: Existing approved tool is changed
- **WHEN** the user requests a change to an existing script in a non-underscore category
- **THEN** the Skill may edit that script in place without routing it through `_candidate/`

### Requirement: Keep project-specific scripts in underscore namespaces

When a newly authored script is intentionally specific to the current project, scene, or workflow rather than intended for cross-project reuse, the Skill SHALL place it below `.houbridge/python/_project/` by default. The user MAY choose another top-level directory whose name begins with `_`, such as `_project_x` or `_proj_team`. The Skill SHALL treat such user-selected underscore directories as local groupings and SHALL NOT require a fixed taxonomy beyond the `_candidate/` staging rule.

#### Scenario: Project-specific script is authored
- **WHEN** a new script is intentionally tied to the current project
- **THEN** it is placed below `.houbridge/python/_project/` unless the user selected another top-level underscore directory
- **AND** it is not forced into `_candidate/` merely to make it appear reusable

### Requirement: Preserve compatibility with existing workspace scripts

The Skill authoring requirement SHALL NOT make a module docstring a runtime prerequisite for arbitrary existing or user-authored files below `.houbridge/python`. Search and execution SHALL continue to accept such scripts when they otherwise satisfy their respective command contracts.

#### Scenario: Existing script has no module docstring
- **WHEN** an existing user-authored workspace script lacks a module docstring
- **THEN** Local Script Search may return the script without a `description` field
- **AND** the missing description alone does not make the script invalid
