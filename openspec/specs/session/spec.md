# Session Feature Specification

## Purpose

Define discovery, inspection, reuse, and local launch of Houdini sessions without binding Houbridge to a Houdini license edition. Command JSON schemas are specified separately.

## Requirements

### Requirement: Inspect a reachable Houdini session generically

Session inspection SHALL use one Houdini-side probe for supported GUI and headless sessions. It SHALL obtain the actual Houdini application version, native license category, active Hip path when available, selected local port, whether the session is headless, and the current operating-system process id needed by internal target coordination, without inferring those values from executable name or launch path. Host-side session resolution SHALL combine that PID with an operating-system process-start identity or equivalent incarnation value when a subsystem such as History needs to distinguish PID reuse. Public `session info` SHALL project only the fields defined by its command contract; PID/incarnation identity MAY remain internal. `headless` SHALL be derived from Houdini UI availability and SHALL be `true` when the UI is unavailable.

#### Scenario: Inspect a Commercial session
- **WHEN** the configured local Houdini openport is reachable
- **THEN** the same generic probe reports the current application version and native Commercial license category

#### Scenario: Inspect an Apprentice session
- **WHEN** the reachable Houdini process is using Apprentice
- **THEN** the same probe is used
- **AND** no Apprentice-specific connection path is required

#### Scenario: Scene has no saved Hip path
- **WHEN** the current scene is untitled or the native Hip path cannot represent a saved project
- **THEN** Session inspection still succeeds without inventing a saved project identity

#### Scenario: Inspect a headless session
- **WHEN** the reachable Houdini process reports that its UI is unavailable
- **THEN** Session inspection reports `headless` as `true`
- **AND** version, license category, active Hip path, and port use the same probe contract

#### Scenario: Target coordination needs process identity
- **WHEN** Execution or Task needs to serialize or bind work to the reachable Houdini process
- **THEN** the same session/target probe provides the current operating-system PID internally
- **AND** public `session info` does not add PID unless its command contract explicitly requires it

#### Scenario: History needs process-incarnation identity
- **WHEN** History resolves the session database for a reachable Houdini process
- **THEN** host-side session resolution provides PID plus process-start/incarnation identity
- **AND** a later process reusing the same PID resolves to a different History session key

### Requirement: Reuse an already reachable target when starting a session

Session start SHALL first probe the requested local port. If a compatible Houdini session is already reachable, Houbridge SHALL reuse it and SHALL NOT launch a second process for the same target.

#### Scenario: Target is already reachable
- **WHEN** Session start probes the requested port successfully
- **THEN** the existing Houdini process is reused
- **AND** no new Houdini process is created

### Requirement: Load an explicitly requested HIP file through Session start launch semantics

Session start MAY receive an invocation-local HIP file path for a newly launched Houdini process. The path SHALL be validated for existence/readability only after reuse probing determines that launch is required. When no compatible target is reachable, the launched process SHALL load that file and startup success SHALL not be reported until the normal session probe succeeds. The file path SHALL not become persistent Houbridge configuration.

The existing reuse-first rule SHALL remain authoritative. When a target is already reachable, Session SHALL reuse that process and SHALL NOT load the launch-only file argument into the running scene.

#### Scenario: Launch with a requested HIP file
- **WHEN** no target is reachable and Session start receives a readable HIP file
- **THEN** Houdini is launched with that file loaded
- **AND** the post-start probe reports the active HIP path

#### Scenario: Existing target is reachable with a file option
- **WHEN** a target already responds and Session start also receives a launch file
- **THEN** the existing process is reused
- **AND** the requested launch file is not loaded into that running scene

### Requirement: Launch the selected Houdini process mode without selecting a license edition

When no compatible session is reachable, Session start SHALL launch either the normal Houdini GUI mode or, when headless launch is selected, a Houdini-provided headless Python runtime that can remain available for openport commands. Both modes SHALL open the requested bridge port and SHALL use the same post-launch Session probe. Houbridge SHALL NOT add Apprentice, Indie, Core, Education, or Commercial-specific launch logic.

#### Scenario: Launch a discovered GUI installation
- **WHEN** no explicit executable is selected, headless launch is not requested, and no session is reachable
- **THEN** Houbridge launches the newest discoverable compatible Houdini GUI installation
- **AND** opens the selected local bridge port through a temporary startup payload

#### Scenario: Launch a discovered headless installation
- **WHEN** no explicit executable is selected, headless launch is requested, and no session is reachable
- **THEN** Houbridge launches the compatible headless Houdini Python runtime from the selected installation
- **AND** enables background handling of openport commands
- **AND** opens the selected local bridge port before reporting startup success

#### Scenario: Launch an explicit executable or tool selector
- **WHEN** an explicit executable/tool selector is configured or supplied for the selected launch mode
- **THEN** Session resolves and launches the corresponding process through that mode's normal path
- **AND** its path is not used to infer the active license category

### Requirement: Discover SideFX tools from explicit settings, Houdini environment, PATH, and Windows installations

Tool discovery SHALL allow `hcommand`, the Houdini GUI executable, and the corresponding headless Houdini Python runtime to be resolved without requiring an already-configured Houdini shell. Explicit tool selection SHALL take precedence. A usable `HFS` SHALL be consulted when present, required tool names MAY be resolved from `PATH`, and on Windows the standard Side Effects Software installation directories SHALL be searched when necessary, choosing the newest compatible installation. This specification does not require unverified platform-specific installation-directory discovery outside Windows.

#### Scenario: Explicit hcommand is configured
- **WHEN** the explicit path exists
- **THEN** it is used before automatic discovery

#### Scenario: Explicit launch tool is missing
- **WHEN** a caller explicitly selects a Houdini executable/tool that cannot resolve the executable required by the selected launch mode
- **THEN** Session reports a structured executable-not-found failure
- **AND** does not silently launch a different edition or installation

#### Scenario: Tool is available through HFS or PATH
- **WHEN** no explicit override is supplied and the required SideFX executable can be resolved from the effective `HFS` installation or process `PATH`
- **THEN** Session may use that executable without requiring Windows installation-directory fallback

#### Scenario: hcommand is not on PATH on Windows
- **WHEN** no explicit path is set and standard Houdini installations exist
- **THEN** discovery searches the Side Effects Software installation directories
- **AND** selects the newest installation containing the required tools

### Requirement: Derive a compatible subprocess environment

When Houbridge resolves a SideFX executable from a Houdini installation, subprocess execution SHALL receive environment state sufficient for SideFX command-line tools to run consistently, including deriving `HFS` from the installation when needed.

#### Scenario: hcommand is resolved from a Houdini bin directory
- **WHEN** the current process does not already provide a usable `HFS`
- **THEN** the launched SideFX subprocess receives `HFS` derived from that installation

### Requirement: Select sessions by explicit port

Session target selection SHALL use the configured port or an invocation-local port override.

#### Scenario: Use the default port
- **WHEN** no per-invocation port is supplied
- **THEN** the effective configured port is used

#### Scenario: Use a one-shot port override
- **WHEN** Session start or another permitted operation supplies a port override
- **THEN** only that invocation uses the override
- **AND** persistent configuration is unchanged

### Requirement: Avoid SideFX license-client port 1714 as the bridge default

The generated default bridge port SHALL remain 18888 and SHALL NOT reuse the standard SideFX license-client port 1714.

#### Scenario: Use generated configuration
- **WHEN** the user accepts the generated Session configuration
- **THEN** Houbridge targets local port 18888
- **AND** does not attempt to use 1714 as the Houdini openport default

### Requirement: Bound session startup and polling

Session start SHALL use configured startup timeout and polling interval. If Houbridge launches a Houdini process but the requested openport does not become reachable before the timeout, it SHALL terminate the process it launched before returning failure.

#### Scenario: Launch never opens the target port
- **WHEN** startup timeout expires
- **THEN** the newly launched process is terminated
- **AND** the failed launch is not reported as a reusable Session

### Requirement: Preserve launched Houdini across unrelated CLI interruption on Windows

A Houdini GUI process intentionally launched by Session start on Windows SHALL be isolated from later console Ctrl+C handling so that interrupting another Houbridge CLI process does not terminate the GUI session.

#### Scenario: Later CLI receives Ctrl+C
- **WHEN** Houdini was launched by an earlier successful Session start
- **THEN** that Houdini process remains running

### Requirement: Generate Session probe scripts under the Houdini script boundary

Session inspection and port-opening helper source SHALL use focused Houdini-side scripts below `houbridge/houdini/scripts/session/` rather than embedding the full probe body in host orchestration code.

#### Scenario: Session info is requested
- **WHEN** host-side Session code prepares the native Houdini probe
- **THEN** the probe implementation comes from the Session injected-script module
- **AND** the host service only supplies invocation-specific paths/parameters and parses the result
