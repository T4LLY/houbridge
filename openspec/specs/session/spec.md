# Session Feature Specification

## Purpose

Define inspection, registration, attachment, primary selection, and local launch of Houdini sessions without binding Houbridge to a Houdini license edition. Command JSON schemas are specified separately.

## Requirements

### Requirement: Inspect a registered reachable Houdini session generically

Session inspection SHALL use one Houdini-side probe for supported GUI and headless sessions. It SHALL obtain the actual Houdini application version, native license category, active Hip path when available, selected local port, whether the session is headless, and the current operating-system process id, without inferring those values from executable name or launch path. Host-side session resolution SHALL combine that PID with an operating-system process-start identity or equivalent incarnation value when a subsystem such as History needs to distinguish PID reuse. `headless` SHALL be derived from Houdini UI availability and SHALL be `true` when the UI is unavailable.

#### Scenario: Inspect a Commercial session
- **WHEN** a registered local Houdini session is reachable
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
- **AND** version, license category, active Hip path, port, and PID use the same probe contract

#### Scenario: History needs process-incarnation identity
- **WHEN** History resolves the session database for a reachable Houdini process
- **THEN** host-side session resolution provides PID plus process-start/incarnation identity
- **AND** a later process reusing the same PID resolves to a different History session key

### Requirement: Store runtime Session registry state globally

Session registration SHALL be runtime operational state rather than user configuration. Houbridge SHALL store the registry at `<data-dir>/sessions.json` below the configured global `[storage].data_dir`. The registry SHALL be shared across working directories.

The registry SHALL represent the primary selection separately from numbered session records:

```json
{
  "primary": 3,
  "sessions": {
    "1": {
      "port": 49152,
      "pid": 12340
    },
    "3": {
      "port": 49154,
      "pid": 18744
    }
  }
}
```

`primary` SHALL always be present and SHALL contain either one registered session number or `null` when no primary is selected. No individual session record SHALL carry a duplicate primary flag. Each session record SHALL retain at least the auto-selected openport and Houdini process PID.

Cross-process Session registry mutation SHALL use a process-coordination lock. Waiting to acquire that lock SHALL be bounded by `[houdini].lock_timeout_seconds`; expiration SHALL fail the operation rather than block indefinitely.

#### Scenario: Commands run from different directories
- **WHEN** two commands use different current working directories
- **THEN** both resolve Session registration from the same global `<data-dir>/sessions.json`

#### Scenario: Registry contains multiple sessions
- **WHEN** more than one Houdini process has been registered
- **THEN** each process has one positive integer session number
- **AND** `primary` remains a single registry-level selection

### Requirement: Create a new process without reuse probing

`session new` SHALL always launch a new Houdini process or selected headless Houdini runtime. It SHALL NOT reuse an already-running process and SHALL NOT perform an "already started" decision before launch.

Before allocating a session number, Session SHALL check the recorded PIDs in the registry and remove entries whose processes are no longer alive. If stale cleanup removes the session referenced by `primary`, Session SHALL unset `primary`. It SHALL NOT promote another existing session automatically.

After stale cleanup, the newly launched process SHALL receive the smallest unused positive session number. On first-ever registry creation, the first successful session SHALL be session `1` and SHALL automatically become primary. If stale cleanup leaves zero live sessions, the newly created session SHALL become primary even when the registry file already exists. If a registry already exists without a primary and at least one live session remains, later `session new` operations SHALL NOT automatically create a new primary.

#### Scenario: Start the first registered process
- **WHEN** no Session registry has previously existed
- **THEN** a successful `session new` creates session `1`
- **AND** records `primary` as `1`

#### Scenario: Stale number is available
- **WHEN** stale cleanup makes session number `2` unused while higher live numbers remain
- **THEN** the next successfully created process is assigned session `2`

#### Scenario: Primary process died while other live sessions remain
- **WHEN** stale cleanup discovers that the primary PID is no longer alive
- **AND** at least one other live session remains
- **THEN** its registry entry is removed
- **AND** `primary` is unset
- **AND** no remaining or newly created session becomes primary automatically

#### Scenario: Stale cleanup leaves no live sessions
- **WHEN** stale cleanup removes every previously registered session before `session new` allocates a number
- **THEN** the newly created session becomes `primary`

### Requirement: Attach an existing process through a manually opened local port

`session attach PORT` SHALL register an already-running local Houdini process without launching or installing anything into Houdini. The target process SHALL already expose an openport; the documented manual workflow SHALL be to execute `openport -a -q` in the target Houdini Textport and pass the printed port to Houbridge. Houbridge SHALL NOT attempt to discover arbitrary unopened Houdini processes or bootstrap an openport into them.

Attachment SHALL use the normal Houdini Session probe and SHALL validate the target across repeated probing and operating-system process-incarnation reads before registry mutation. The requested port SHALL be reported by that same Houdini process. Stale registry cleanup and session-number allocation SHALL follow the same rules as `session new`. If cleanup leaves zero live sessions, the attached process SHALL become primary; if live sessions remain, attachment SHALL preserve the current primary value.

A single live Houdini process SHALL have at most one Session record. Reattaching the same registered PID and port SHALL be idempotent. Attempting to attach another openport belonging to a Houdini process that is already registered SHALL fail without modifying that record.

#### Scenario: Existing Houdini is prepared manually
- **WHEN** a user opens a port with `openport -a -q` in an already-running Houdini
- **AND** invokes `session attach` with that port
- **THEN** Houbridge registers that process without starting a second Houdini

#### Scenario: Port identity changes while attaching
- **WHEN** the probed PID, reported openport, or process incarnation changes during validation
- **THEN** attachment fails before the Session registry is mutated

#### Scenario: Another live session already exists without a primary
- **WHEN** attachment begins with at least one live registered session and `primary` is `null`
- **THEN** the new Session record is added
- **AND** `primary` remains `null`

### Requirement: Let Houdini choose the openport

Houbridge SHALL NOT expose a persistent user-configurable bridge port and SHALL NOT search the host for a free bridge port. During `session new` bootstrap, Houdini SHALL execute `openport -a` and choose an available local port. `session attach` MAY accept an already-open runtime port as its required positional target, but Houbridge SHALL NOT choose that port or open it in the existing process. Houbridge SHALL persist the validated port together with the Houdini process PID in the Session registry.

The automatically selected port is runtime connection state only. Normal Houdini-facing commands SHALL resolve it from the selected session record rather than from configuration or a `--port` option.

#### Scenario: Create a session
- **WHEN** the launched Houdini bootstrap executes `openport -a`
- **THEN** Houdini selects the available bridge port
- **AND** Houbridge records that returned port with the process PID

#### Scenario: User attempts to choose a port
- **WHEN** public Session or Houdini-facing command syntax is defined
- **THEN** no `--port` option or persistent default bridge-port setting is provided

### Requirement: Resolve target by explicit session or primary

Houdini-facing commands that accept `--session` SHALL use the explicitly requested registered session when present. Otherwise they SHALL resolve the registry `primary` selection. `session info` is the deliberate exception: without `--session`, it inspects all registered sessions.

A selected registry entry SHALL be validated before dispatch by confirming the recorded PID is alive and that probing the recorded port identifies that same Houdini PID. A recycled port alone SHALL NOT make a stale entry valid. Commands SHALL NOT silently switch to another session when the selected session is unavailable.

#### Scenario: Explicit session is selected
- **WHEN** a Houdini-facing command receives `--session 3`
- **THEN** it resolves session `3` from the global registry
- **AND** uses the recorded port only after validating the recorded process

#### Scenario: Session option is omitted
- **WHEN** a Houdini-facing command other than `session info` omits `--session`
- **THEN** it resolves the current `primary` session

#### Scenario: No primary exists
- **WHEN** a Houdini-facing command omits `--session` while the registry has no primary
- **THEN** Houbridge reports the missing primary and terminates the operation without dispatch
- **AND** it does not select the lowest numbered session automatically

### Requirement: Promote a live session explicitly

Once at least one live Session record already exists, Session promotion SHALL be the only public operation that replaces or creates the primary selection. Automatic primary assignment is limited to `session new` or `session attach` when stale cleanup leaves zero live Session records. `session promote N` SHALL validate that session `N` is registered and live before setting `primary` to `N`.

#### Scenario: Replace the primary selection
- **WHEN** a live session `3` is promoted while session `1` is primary
- **THEN** `primary` becomes `3`
- **AND** session numbers themselves do not change

### Requirement: Load an explicitly requested HIP file when creating a session

`session new` MAY receive an invocation-local HIP file path. The path SHALL be validated for existence/readability before launch. The launched process SHALL load that file and startup success SHALL not be reported until the automatically selected openport is reachable and the normal session probe succeeds. The file path SHALL not become persistent Houbridge configuration.

#### Scenario: Launch with a requested HIP file
- **WHEN** `session new` receives a readable HIP file
- **THEN** the new Houdini process opens that file
- **AND** the post-start probe reports the active HIP path

### Requirement: Launch the selected Houdini process mode without selecting a license edition

`session new` SHALL launch either the normal Houdini GUI mode or, when headless launch is selected, a Houdini-provided headless Python runtime that can remain available for openport commands. Both modes SHALL bootstrap `openport -a` and SHALL use the same post-launch Session probe. Houbridge SHALL NOT add Apprentice, Indie, Core, Education, or Commercial-specific launch logic.

#### Scenario: Launch a GUI session
- **WHEN** headless launch is not requested
- **THEN** Houbridge starts a new Houdini GUI process
- **AND** the bootstrap obtains an automatically selected openport before success is reported

#### Scenario: Launch a headless session
- **WHEN** headless launch is requested
- **THEN** Houbridge starts a new compatible headless Houdini runtime
- **AND** enables background handling of openport commands
- **AND** obtains an automatically selected openport before reporting startup success

### Requirement: Resolve the Session new launch executable by explicit override, global configuration, then default

For `session new`, the Houdini launch executable SHALL resolve in this order:

1. invocation `--hcommand PATH`;
2. global `[houdini].hcommand` when non-empty;
3. executable name `houdini` for the normal GUI launch path.

`--hcommand` and `[houdini].hcommand` SHALL identify an executable only and SHALL NOT contain command-line arguments. For `--headless`, Session SHALL resolve the corresponding compatible headless Houdini runtime rather than launching the GUI executable as a visible process. A local `<cwd>/.houbridge.toml` SHALL NOT override the global launch executable.

SideFX transport tooling required after bootstrap MAY be resolved from the selected Houdini installation, a usable `HFS`, or `PATH`; normal commands SHALL not expose a per-invocation transport-executable override.

Standard installation discovery SHALL include the platform-default Houdini installation roots used by supported desktop platforms. On macOS, Houbridge SHALL inspect `/Applications/Houdini/HoudiniX.Y.ZZZ` installations through their Houdini framework HFS resource directory (`Frameworks/Houdini.framework/Versions/Current/Resources`, including the equivalent framework `Resources` symlink when present).

#### Scenario: Explicit launch executable is supplied
- **WHEN** `session new --hcommand PATH` supplies a valid executable path
- **THEN** that executable takes precedence over global configuration and the default

#### Scenario: Global launch executable is configured
- **WHEN** `--hcommand` is omitted and global `[houdini].hcommand` is non-empty
- **THEN** that configured executable is used

#### Scenario: No launch executable override exists
- **WHEN** neither invocation nor global configuration selects an executable
- **THEN** Session resolves the default executable name `houdini` for the normal GUI launch path

### Requirement: Derive a compatible subprocess environment

When Houbridge resolves SideFX executables from a Houdini installation, subprocess execution SHALL receive environment state sufficient for SideFX command-line tools to run consistently, including deriving `HFS` from the installation when needed.

#### Scenario: SideFX tools are resolved from a Houdini installation
- **WHEN** the current process does not already provide a usable `HFS`
- **THEN** launched SideFX subprocesses receive `HFS` derived from that installation

### Requirement: Bound session creation and polling

`session new` SHALL use configured startup timeout and polling interval. If Houbridge launches a Houdini process but bootstrap does not return a usable automatically selected openport before the timeout, it SHALL terminate the process it launched before returning failure and SHALL NOT register the failed session.

#### Scenario: Launch never opens an automatic port
- **WHEN** startup timeout expires
- **THEN** the newly launched process is terminated
- **AND** no Session registry entry is created for that failed launch

### Requirement: Preserve Session failure diagnostics

If Session bootstrap or post-bootstrap Session probing fails, Houbridge SHALL preserve the failed private Temporary Workspace and SHALL include its path in the returned error detail. The retained workspace SHALL contain the generated Session script/request context and a concise error record; Session probing SHALL also preserve captured synchronous hcommand stdout/stderr when available. Successful Session bootstrap and probing SHALL continue to remove their private Temporary Workspaces.

#### Scenario: Session probe fails before publishing its result
- **WHEN** the injected Session probe or its synchronous hcommand invocation fails
- **THEN** the failed probe workspace remains available below the managed Temporary Workspace root
- **AND** the public error detail identifies that diagnostic workspace
- **AND** captured hcommand stdout/stderr are retained when hcommand returned them

#### Scenario: Session bootstrap and probe succeed
- **WHEN** `session new` completes Session bootstrap and probing successfully
- **THEN** the private bootstrap and probe workspaces are removed

### Requirement: Preserve launched Houdini across unrelated CLI interruption on Windows

A Houdini GUI process intentionally launched by `session new` on Windows SHALL be isolated from later console Ctrl+C handling so that interrupting another Houbridge CLI process does not terminate the GUI session.

#### Scenario: Later CLI receives Ctrl+C
- **WHEN** Houdini was launched by an earlier successful `session new`
- **THEN** that Houdini process remains running

### Requirement: Generate Session bootstrap and probe scripts under the Houdini script boundary

Session inspection and `openport -a` bootstrap helper source SHALL use focused Houdini-side scripts below `houbridge/houdini/scripts/session/` rather than embedding the full probe body in host orchestration code.

#### Scenario: Session info is requested
- **WHEN** host-side Session code prepares the native Houdini probe
- **THEN** the probe implementation comes from the Session injected-script module
- **AND** the host service only supplies invocation-specific paths/parameters and parses the result
