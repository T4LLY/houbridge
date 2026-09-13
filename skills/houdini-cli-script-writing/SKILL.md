---

name: houdini-cli-script-writing
description: Write Houdini Python scripts intended to run through houbridge. Use this skill when creating HOM-based scripts for scene inspection, node creation, parameter changes, batch operations, or reusable Houdini tooling.
---

# Houbridge Script Writing

Use this skill to write Houdini Python scripts intended to run through houbridge.

This skill only covers writing the code.

Execution, Session selection, Task inspection, Resource retrieval, Capture, and History operations are handled by separate skills.

## Guidelines

* Use the `hou` module for Houdini operations.
* Write complete executable Python files.
* Identify target nodes and parameters explicitly.
* Prefer reusable operations that can process multiple nodes or values in one execution.
* Avoid unnecessary full-scene traversal.
* Do not make failures look like successful results. Raise an exception when appropriate.
* Avoid hard-coding values that callers are expected to change.
* Use command-line arguments for configurable inputs.
* Store reusable scripts in `.houbridge/python`.
* Keep search descriptions concise and put detailed usage information in `--help`.

## Search Summary

Reusable scripts stored in `.houbridge/python` should define a concise module docstring.

The module docstring is the script's search summary and is used by `houbridge search script`.

Describe what the script does, not how it is implemented.

```python
"""Apply parameter values to multiple Houdini nodes from a JSON specification."""

import hou
```

Keep the module docstring short enough to work as a search result summary.

Do not fill it with:

* Detailed argument documentation
* Implementation details
* Execution history
* Long examples
* Internal architecture notes

The module docstring is the canonical short description of the script.

When using `argparse`, reuse it as the command help description:

```python
"""Apply parameter values to multiple Houdini nodes from a JSON specification."""

import argparse

parser = argparse.ArgumentParser(
    description=__doc__,
)
```

Do not introduce a separate custom summary field when the module docstring is sufficient.

## Arguments

Reusable scripts should expose configurable values as command-line arguments rather than embedding them directly in the source.

For simple scripts, `sys.argv` is acceptable.

```python
"""Print information about multiple Houdini nodes."""

import json
import sys

import hou

node_paths = sys.argv[1:]

results = []

for node_path in node_paths:
    node = hou.node(node_path)

    if node is None:
        raise RuntimeError(f"Node not found: {node_path}")

    results.append(
        {
            "path": node.path(),
            "type": node.type().name(),
        }
    )

print(json.dumps(results))
```

For reusable scripts with multiple options or non-trivial input formats, prefer `argparse`.

```python
"""Apply parameter values to multiple Houdini nodes from a JSON specification."""

import argparse

parser = argparse.ArgumentParser(
    description=__doc__,
)

parser.add_argument(
    "--spec",
    required=True,
    help="Path to the JSON specification containing node paths and parameter values.",
)

args = parser.parse_args()
```

Each public argument and option should have a concise `help` description.

The purpose of `--help` is to describe how to use the script after it has been discovered through `houbridge search script`.

Use this separation:

* Module docstring: what the script does
* `--help`: how to use it

## Reusable Operations

Prefer scripts that perform useful operations over collections of inputs rather than scripts that only handle one fixed node or one fixed action.

Good reusable scripts include operations such as:

* Creating multiple nodes and connections from a specification
* Applying parameter values to multiple nodes
* Inspecting multiple nodes in one execution
* Validating multiple nodes and collecting errors
* Editing flags, colors, names, or metadata in batches
* Building or modifying an entire network from structured input
* Collecting geometry or network information from multiple targets

When several related operations naturally belong together, prefer one coherent batch-oriented script over many single-operation scripts.

Do not turn unrelated operations into one large generic script.

## Structured Input

For complex reusable operations, prefer structured input over large numbers of positional arguments.

JSON is suitable for specifications containing multiple nodes, parameters, connections, or operations.

Example specification:

```json
{
  "nodes": [
    {
      "path": "/obj/geo1/box1",
      "parameters": {
        "sizex": 2.0,
        "sizey": 1.0
      }
    },
    {
      "path": "/obj/geo1/box2",
      "parameters": {
        "sizex": 4.0,
        "sizey": 2.0
      }
    }
  ]
}
```

Keep the accepted structure explicit in `--help` or provide a concise usage example there when the format is not obvious.

## Output

Write only results needed by the caller to stdout.

Use short plain-text output for simple results.

Use JSON when returning structured information, collections, or multiple results.

```python
"""Return basic information about multiple Houdini nodes as JSON."""

import json
import sys

import hou

results = []

for node_path in sys.argv[1:]:
    node = hou.node(node_path)

    if node is None:
        raise RuntimeError(f"Node not found: {node_path}")

    results.append(
        {
            "path": node.path(),
            "type": node.type().name(),
        }
    )

print(json.dumps(results))
```

Prefer one structured result over many loosely formatted lines when the caller is expected to consume the output programmatically.

Do not emit large amounts of data to stdout unnecessarily.

## Long-running Scripts

When reporting progress from a long-running operation, flush each progress message explicitly.

```python
print("processing", flush=True)
```

Write progress as newline-delimited messages.

Do not use `\r` to rewrite the current line.

Do not emit terminal control sequences.

Keep progress output concise so that it does not overwhelm the final result.

## Errors

Fail explicitly when required inputs, nodes, parameters, or other prerequisites are missing.

```python
node = hou.node("/obj/geo1")

if node is None:
    raise RuntimeError("Node not found: /obj/geo1")
```

For batch operations, include enough context to identify the failed item.

```python
for node_path in node_paths:
    node = hou.node(node_path)

    if node is None:
        raise RuntimeError(f"Node not found: {node_path}")
```

Do not catch broad exceptions only to suppress them.

Do not silently skip invalid inputs unless skipping them is an explicit part of the script's contract.

## Scope

This skill does not cover:

* Running `houbridge exec`
* `--async`
* Task inspection
* Resource retrieval
* Session management
* Capture
* History search
* Houdini documentation lookup

Use the corresponding skills for those operations.
