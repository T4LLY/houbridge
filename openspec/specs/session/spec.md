# Session Feature Specification

## Purpose

Define discovery, inspection, reuse, and local launch of Houdini GUI sessions without binding Houbridge to a Houdini license edition. Command JSON schemas are specified separately.

## Requirements

### Requirement: Inspect a reachable Houdini session generically

Session inspection SHALL use one Houdini-side probe for all supported GUI license categories. It SHALL report the actual Houdini application version, native license category, active Hip path when available, and the selected local port without inferring edition from executable name or launch path.

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

### Requirement: Reuse an already reachable target when starting a session

Session start SHALL first probe the requested local port. If a compatible Houdini session is already reachable, Houbridge SHALL reuse it and SHALL NOT launch a second process for the same target.

#### Scenario: Target is already reachable
- **WHEN** Session start probes the requested port successfully
- **THEN** the existing Houdini process is reused
- **AND** no new Houdini GUI process is created

### Requirement: Launch Houdini without selecting a license edition

When no compatible session is reachable, Session start SHALL launch a Houdini GUI executable generically and provide invocation-local HScript that opens the requested bridge port. Houbridge SHALL NOT add Apprentice, Indie, Core, Education, or Commercial-specific launch logic.

#### Scenario: Launch a discovered installation
- **WHEN** no explicit GUI executable is configured and no session is reachable
- **THEN** Houbridge launches the newest discoverable compatible Houdini GUI installation
- **AND** opens the selected local bridge port through a temporary HScript payload

#### Scenario: Launch an explicit executable
- **WHEN** an explicit Houdini GUI executable is configured or supplied
- **THEN** that executable is launched through the same generic path
- **AND** its path is not used to infer the active license category

### Requirement: Discover SideFX tools from explicit settings, native environment, and standard installations

Tool discovery SHALL allow `hcommand` and the Houdini GUI executable to be resolved without requiring an already-configured Houdini shell. Explicit tool configuration SHALL take precedence. Standard Houdini environment information such as `HFS` MAY be used for native discovery. On Windows, standard Side Effects Software installation directories SHALL be searched when necessary, choosing the newest compatible installation.

#### Scenario: Explicit hcommand is configured
- **WHEN** the explicit path exists
- **THEN** it is used before automatic discovery

#### Scenario: Explicit GUI executable is missing
- **WHEN** a caller explicitly selects a Houdini executable that does not exist
- **THEN** Session reports a structured executable-not-found failure
- **AND** does not silently launch a different edition or installation

#### Scenario: hcommand is not on PATH on Windows
- **WHEN** no explicit path is set and standard Houdini installations exist
- **THEN** discovery searches the Side Effects Software installation directories
- **AND** selects the newest installation containing the required tools

### Requirement: Derive a compatible subprocess environment

When Houbridge resolves a SideFX executable from a Houdini installation, subprocess execution SHALL receive environment state sufficient for SideFX command-line tools to run consistently, including deriving `HFS` from the installation when needed.

#### Scenario: hcommand is resolved from a Houdini bin directory
- **WHEN** the current process does not already provide a usable `HFS`
- **THEN** the launched SideFX subprocess receives `HFS` derived from that installation

### Requirement: Keep session targets loopback-only

Session target selection SHALL use the local host and an explicit port. Houbridge SHALL NOT expose a persistent configurable remote host feature.

#### Scenario: Use the default port
- **WHEN** no per-invocation port is supplied
- **THEN** the effective configured local port is used

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
