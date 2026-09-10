# Search Command Specification

## Purpose

Define public syntax, options, score formatting, and JSON response contracts for live Python/VEX code search, local script search, and live Houdini node search.

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
      "score": 317.540323
    }
  ]
}
```

Each hit SHALL contain exactly `path`, `node_type`, `resource`, and `score`. Searchable source code SHALL NOT be copied into the public hit JSON; the complete source SHALL be available through `resource`.

For normal lexical/hybrid search, `score` SHALL use the shared public RRF formatter. For `--like`, `score` SHALL use the shared public dense-similarity formatter. All public Search scores SHALL use the common score-formatting requirement defined by the Search feature specification.

#### Scenario: Python hit is returned
- **WHEN** a Python code entry ranks in the result set
- **THEN** its code body is stored as a Resource
- **AND** the hit contains no inline `source` or `code` field

### Requirement: Expose local script semantic search with a minimal result envelope

The syntax SHALL be:

```text
houbridge search script QUERY [--top-k INTEGER]
```

`QUERY` is required. `--top-k` SHALL be `1..50` and default to `10`.

Success SHALL contain exactly one top-level field, `hits`. Each script hit SHALL contain `path` and `score`. When the indexed Python file has a non-empty module description, the hit SHALL also contain `description`:

```json
{
  "hits": [
    {
      "path": ".houbridge/python/build.py",
      "score": 301.278910,
      "description": "Creates preview geometry and configures the material network."
    }
  ]
}
```

`description` SHALL be omitted rather than emitted as `null` when the file has no module description. Internal semantic-unit metadata such as symbol kind, symbol name, qualified name, line range, namespace, entry id, and content hash SHALL NOT be emitted by this command.

#### Scenario: Search a described local script
- **WHEN** a query produces a semantic match from a Python file with a non-empty module description
- **THEN** the result contains only `hits`
- **AND** the hit contains exactly `path`, `score`, and `description`

#### Scenario: Search an undescribed local script
- **WHEN** a query produces a semantic match from a Python file without a module description
- **THEN** the hit contains exactly `path` and `score`
- **AND** no `description` field is emitted

#### Scenario: No script hit exists
- **WHEN** the script query has no result
- **THEN** success is `{"hits":[]}`

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
