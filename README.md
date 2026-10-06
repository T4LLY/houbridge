# Houbridge

Houbridge is a CLI for controlling and inspecting local SideFX Houdini sessions. It can run Houdini Python, manage sessions, capture images, and search scene code or nodes.

> [!NOTE]
> Houbridge is currently pre-beta and intended primarily for personal and experimental use. Version 0.4 is planned to mark the start of the beta phase.

## Requirements

- Python 3.11 or later
- A local SideFX Houdini installation
- [uv](https://docs.astral.sh/uv/)

### No Houdini-side installation

Houbridge does not require a plug-in, package, or persistent service to be installed inside Houdini. It uses Houdini's built-in local `openport` and `hcommand` interface to send scripts at runtime.

### Optional tools

- [`jq`](https://jqlang.org/) — recommended for filtering large Houbridge JSON responses before passing them to an AI agent.
- [`image-prep`](https://github.com/T4LLY/image-prep) — recommended for reducing unnecessary vision input from captures through resizing, cropping, and changed-region extraction. Requires ImageMagick 7 with `magick` available on `PATH`.
- **OpenCode:** [`opencode-pty`](https://github.com/shekohex/opencode-pty) — recommended for running long synchronous Houbridge commands as background tasks with completion notification.

If the agent does not reliably infer the appropriate background-task tool from the generic guidance, add the concrete tool name used by that harness to the Houbridge Skill, such as `pty_spawn` for `opencode-pty`.

## Installation

Clone the repository and install its `houbridge` command with uv:

```bash
git clone <repository-url>
cd houbridge
uv tool install .
```

Verify the installation:

```bash
houbridge --help
```

For development without installing the command globally, use `uv sync` and prefix commands with `uv run` instead:

```bash
uv sync
uv run houbridge --help
```

### Install AI skills

After the repository is available at `T4LLY/houbridge`, install its bundled Houdini skills with:

```bash
npx skills add T4LLY/houbridge
```

This installs the `houdini-cli-bridge` and `houdini-cli-script-writing` skills for supported AI coding tools.

## Usage

### Start a Houdini session

Start Houdini with a HIP file and register the resulting session:

```bash
houbridge session new --file path/to/scene.hip
houbridge session info
```

When several sessions are registered, use `session promote <number>` to select the default session.

### Attach an existing Houdini session

Houbridge does not install a resident plugin into Houdini. To register a Houdini process that was started outside `houbridge session new`, first open Houdini's Textport and run:

```text
openport -a -q
```

Houdini prints the automatically selected local port. Pass that number to Houbridge:

```bash
houbridge session attach 49153
```

`session attach` does not start Houdini and does not open the port for you. It probes the supplied local port, verifies the Houdini PID and process incarnation, confirms that Houdini reports the same openport, removes registry entries proven stale, and then registers the process.

Attaching the same registered port again is idempotent. If the same Houdini process is already registered through another port, attach fails instead of creating a duplicate session.

The attached process becomes primary only when no live registered sessions remain. Otherwise the existing primary selection is preserved; use `houbridge session promote <number>` when you want to change it.

### Inspect and save the HIP file

Inspect the active scene file or save it to its existing path:

```bash
houbridge hip info
houbridge hip save
```

Both commands accept `--session`. `hip save` deliberately has no Save As path; a new unsaved scene is rejected rather than being written implicitly to Houdini's default path. Save results report `status: "saved"` when Houdini wrote the file or `status: "unchanged"` when the existing file had no unsaved changes and was left untouched.

### Run Houdini Python

Create a Python file to execute:

```python
# example.py
import hou

result = {"hip_file": hou.hipFile.path()}
```

Run it in the default registered session:

```bash
houbridge exec --file example.py
```

Use `--session` to target a specific session:

```bash
houbridge exec --file example.py --session 1
```

### Semantic recall

Houbridge is designed to give AI-assisted workflows a local, searchable memory.

- `houbridge history` records managed Python executions and their scene changes for the current Houdini session. Its semantic search helps recall what was done and why.
- `houbridge search script` semantically searches reusable Python tools in `.houbridge/python`, helping you find work created in previous sessions instead of recreating it.

Both commands use hybrid semantic and lexical ranking, so they can retrieve related work even when the search terms do not exactly match.

### Headless camera capture

> [!WARNING]
> Headless camera capture is currently not supported due to a reproducible Houdini 22.0.x Vulkan Flipbook crash. The issue has been reported to SideFX.

### Common commands

```bash
# Inspect the current HIP file.
houbridge hip info

# Capture a viewport image.
houbridge capture viewport

# Search Python code in the current Houdini scene.
houbridge search python "camera"

# Search reusable Python scripts in the workspace.
houbridge search script "export"

# List recent actions in the current session.
houbridge history list
```

Run `--help` at any command level to see its available options:

```bash
houbridge capture viewport --help
```

## Related tools

`houbridge`, `houdocs`, and `houlayout` are separate CLIs designed for agent orchestration. Each can be assigned to the agent that needs its capabilities, keeping tool surfaces small and token-efficient.

### Houbridge

`houbridge` provides the general Houdini runtime interface: session management, execution, capture, resources, and scene access.

It exposes raw `exec` for workflows that require direct Houdini Python execution.

### Houdocs

`houdocs` provides structured search and retrieval over Houdini documentation.

It can be assigned to agents that only need Houdini API and documentation access without exposing runtime operations.

### Houlayout

`houlayout` is a node-oriented wrapper around Houbridge for inspecting, selecting, and organizing Houdini networks.

It intentionally does not expose raw `exec`, providing agents with a smaller and more constrained command surface.

Because these tools are ordinary CLIs, Houbridge can also be wrapped to create additional task-specific interfaces. A wrapper can expose only the operations required by an agent while deliberately omitting `exec` or other unrestricted capabilities.

This allows orchestration systems to assign different interfaces to different agents instead of exposing the full Houdini control surface to every agent.

In short:

- `houbridge` — general Houdini runtime and execution
- `houdocs` — structured Houdini documentation search
- `houlayout` — constrained node and network operations

## License

[MIT License](LICENSE)