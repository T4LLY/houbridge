---
name: houdini-cli-bridge
description: Execute and control a local SideFX Houdini instance through HOM Python, and retrieve its state as JSON or screenshots.
---

# Houbridge

houbridge is a CLI for inspecting and controlling a running Houdini instance.

## Session
- `houbridge session new [--file <HIP>]` starts a new Houdini session.
- `houbridge session info` shows session numbers. Commands such as `exec` can target a session with `--session <Number>`.
- `houbridge session promote <Number>` sets the Primary session, allowing the `--session` parameter to be omitted.

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

## Other Commands
- `houbridge search <subcommand>`: inspect the current Houdini state
- `houbridge capture`: visual inspection
- `houbridge exec --async`: asynchronous execution
- `houbridge task <subcommand>`: inspect asynchronously executed Tasks

## CLI Help
Do not guess command structure or options.
- `houbridge --help`: inspect available command groups
- `houbridge <command> --help`: inspect available subcommands
- `houbridge <command> <subcommand> --help`: inspect arguments and options

Follow `--help` down to the required command level.