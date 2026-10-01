---
name: houdini-cli-bridge
description: Execute and control a local SideFX Houdini instance through HOM Python, and retrieve its state as JSON or screenshots.
---

# Houbridge

houbridge is a CLI for inspecting and controlling a running Houdini instance.

## Session
- `houbridge session new [--file <HIP>]` starts a new Houdini session.
- To register a Houdini process started outside Houbridge, run `openport -a -q` in that Houdini Textport, then run `houbridge session attach <PORT>` with the printed port. Do not assume attach can open a port in an unprepared process.
- `houbridge session info` shows session numbers. Commands such as `exec` can target a session with `--session <Number>`.
- `houbridge session promote <Number>` sets the Primary session, allowing the `--session` parameter to be omitted.

## HIP File
- `houbridge hip info [--session <Number>]` reports the current HIP path and dirty/new state.
- `houbridge hip save [--session <Number>]` saves only to the existing HIP path when there are unsaved changes. Its result reports `status: "saved"` when a native save ran or `status: "unchanged"` when the file was already clean. It does not perform Save As and rejects a new unsaved scene without an established target.

## Python
- Execute Houdini Python with `houbridge exec --file <PATH>`. Prefer parameterized, reusable tools when practical.
- Store reusable scripts in `.houbridge/python`.
- `houbridge search script <QUERY>` searches for reusable Python tools created in previous work.
- Before implementing something new, consider whether an existing tool can be reused.
- Give reusable scripts a descriptive module docstring and a clear filename that indicate their purpose.

## History
- `houbridge history search <QUERY>` searches previous Houdini actions and execution context.
- `houbridge history list` lists recent actions in reverse chronological order.

## Output and Resources
- When a large JSON result is returned as `{"resource": "<resource-id>"}`, use `houbridge resource` to retrieve only the parts you need.
- When `jq` is available and the needed fields are known, proactively filter Houbridge JSON to only the fields required for the current task. Do not aggressively filter unfamiliar output before understanding its structure.

## Visual Inspection
- Start with `houbridge capture --help`, then inspect the selected capture subcommand's `--help` instead of assuming current options.
- Use `houbridge capture panes` to discover Scene Viewer pane names and pass the selected name with `--pane` to `viewport`, `camera`, or `turntable`.
- When `image-prep` is available, use it proactively to reduce unnecessary vision input from captures. Inspect `image-prep --help` for current capabilities, and prefer resizing, targeted crops, or changed-region extraction when the full image is unnecessary.

## Optional Tools
- For long-running Houbridge commands, use the harness's background task execution with completion steer/notification when available.
- Run the normal synchronous Houbridge command in that background task, continue other work while it runs, and resume from the completion notification instead of polling.
- Prefer this over `houbridge exec --async` when the harness can manage the background process and notify the agent on completion.

## Other Commands
- `houbridge search <subcommand>`: inspect the current Houdini state
- `houbridge exec --async`: asynchronous execution
- `houbridge task <subcommand>`: inspect asynchronously executed Tasks

## CLI Help
Do not guess command structure or options.
- `houbridge --help`: inspect available command groups
- `houbridge <command> --help`: inspect available subcommands
- `houbridge <command> <subcommand> --help`: inspect arguments and options

Follow `--help` down to the required command level.