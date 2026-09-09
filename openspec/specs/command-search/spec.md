# Search Command Specification

## Purpose

Define public syntax, options, and JSON response contracts for live Python/VEX code search, local script search, and live Houdini node search.

## Requirements

### Requirement: Expose live Python and VEX code search with identical syntax

The command syntax SHALL be:

```text
houbridge search python [QUERY] [OPTIONS]
houbridge search vex [QUERY] [OPTIONS]
```

Exactly one of positional `QUERY` or `--like NODE_PATH` SHALL be supplied.

| Option | Constraint / meaning |
| --- | --- |
| `--top-k INTEGER` | `1..50`, default `10`. |
| `--like NODE_PATH` | Use code from the exact source node path as the dense embedding query. |
| `--path TEXT` | Restrict capture/search to an exact node path or Houdini child-name glob. |
| `--recursive` | Include descendants selected by `--path`. |
| `--port INTEGER` | `1..65535`. |
| `--root PATH` | Common runtime option. |
| `--hcommand TEXT` | Common runtime option. |

#### Scenario: Positional query search
- **WHEN** `houbridge search python "create geometry"` is invoked
- **THEN** Python code is searched using the query text

#### Scenario: Like-node search
- **WHEN** `houbridge search vex --like /obj/geo1/wrangle1` is invoked
- **THEN** source code at that exact VEX node is the dense query
- **AND** the source node itself is excluded from returned like-results

#### Scenario: Query mode is ambiguous
- **WHEN** both query and `--like` are provided or both are absent
- **THEN** the command fails with `invalid_code_search_query`

### Requirement: Return Resource-backed live code hits without inline source

Python and VEX search success SHALL use:

```json
{
  "hits": [
    {
      "path": "/obj/geo1/python1",
      "node_type": "python",
      "resource": "<code-resource-id>",
      "score": 9500.0
    }
  ]
}
```

Each hit SHALL contain exactly `path`, `node_type`, `resource`, and `score`. Searchable source code SHALL NOT be copied into the public hit JSON; the complete source SHALL be available through `resource`.

For normal lexical/hybrid search, `score` uses the public normalized RRF score. For `--like`, `score` is the rounded dense similarity value.

#### Scenario: Python hit is returned
- **WHEN** a Python code entry ranks in the result set
- **THEN** its code body is stored as a Resource
- **AND** the hit contains no inline `source` or `code` field

### Requirement: Expose local script semantic search

The syntax SHALL be:

```text
houbridge search script QUERY [--top-k INTEGER]
```

`QUERY` is required. `--top-k` SHALL be `1..50` and default to `10`.

#### Scenario: Search local scripts
- **WHEN** a query is provided
- **THEN** success SHALL use:

```json
{
  "query": "create geometry",
  "root": "E:/project/.houbridge/python",
  "hits": [
    {
      "path": ".houbridge/python/build.py",
      "score": 0.75,
      "kind": "function",
      "symbol": "build",
      "qualname": "build",
      "start_line": 4,
      "end_line": 6
    }
  ]
}
```

`path` and `score` are required for each script hit. `kind`, `symbol`, `qualname`, `start_line`, and `end_line` are optional and emitted only when metadata exists.

#### Scenario: No script hit exists
- **WHEN** the script query has no result
- **THEN** `query` and `root` remain present
- **AND** `hits` is an empty array

### Requirement: Expose live node search

The syntax SHALL be:

```text
houbridge search node QUERY [--top-k INTEGER] [--path TEXT] [--recursive] [--port INTEGER] [--root PATH] [--hcommand TEXT]
```

`QUERY` is required. `--top-k` SHALL be `1..100` and default to `20`. `--path` restricts selection to an exact Houdini node path or child-name glob. `--recursive` includes descendants of selected nodes.

Normal success SHALL use:

```json
{
  "hits": [
    {
      "path": "/obj/geo1",
      "name": "geo1",
      "type": "geo",
      "category": "Object"
    }
  ]
}
```

Each node hit SHALL contain exactly `path`, `name`, `type`, and `category`.

#### Scenario: Node query has no matches
- **WHEN** no selected node matches the query
- **THEN** success is `{"hits":[]}`

### Requirement: Apply common Resource fallback to large Search envelopes

A Search command SHALL construct the logical payload defined above and then use the common Output Policy. A whole-result fallback SHALL use:

```json
{"resource":"<resource-id>"}
```

The Resource SHALL contain the complete logical payload.

#### Scenario: Large node hit list
- **WHEN** the complete node result exceeds the common inline budget
- **THEN** the command emits the minimal Resource fallback
- **AND** the Resource contains the complete `hits` object
