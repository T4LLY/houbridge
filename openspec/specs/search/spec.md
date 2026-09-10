# Search Feature Specification

## Purpose

Define live Houdini node search, live Python/VEX code search, and workspace-local Python script semantic search while keeping live search transient and local script source authoritative in the filesystem. Command JSON schemas are specified separately.

## Requirements

### Requirement: Use an explicit live-code extractor registry

Live code search SHALL use an explicit registry that identifies supported Python and VEX node types/parameters. It SHALL NOT treat arbitrary text parameters as executable code merely because they contain text.

The built-in registry SHALL contain at least these mappings:

| Extractor | Language | Node type names | Parameter names |
| --- | --- | --- | --- |
| `vex-wrangle` | `vex` | `attribwrangle`, `pointwrangle`, `primitivewrangle`, `vertexwrangle`, `volumewrangle`, `wrangle` | `snippet` |
| `python-node` | `python` | `python`, `pythonscript` | `python`, `code`, `script` |

Node-type matching SHALL be case-insensitive. A namespaced Houdini node type SHALL match when either its exact type name or the portion before the first `::` matches a configured node type name. For each matching extractor, Houbridge SHALL inspect only its configured parameter names, read existing parameters through their raw value, skip parameters that cannot be read, and skip source that is empty or whitespace-only. Multiple selected references to the same Houdini node SHALL be deduplicated by `hou.Node.sessionId()` for that live capture.

#### Scenario: Supported VEX node is encountered
- **WHEN** a registered VEX-bearing Houdini node is scanned
- **THEN** the configured code parameter is extracted with language `vex`

#### Scenario: Supported Python node is encountered
- **WHEN** a registered Python-bearing Houdini node is scanned
- **THEN** the configured Python source is extracted with language `python`

#### Scenario: Unsupported text parameter is encountered
- **WHEN** a node contains unregistered text parameters
- **THEN** those parameters are not indexed as Python or VEX source

### Requirement: Search current live Python and VEX code

Live Python/VEX search SHALL capture currently relevant code from the running Houdini scene and rank the current capture.

#### Scenario: Search live Python code
- **WHEN** a Python query is submitted
- **THEN** current registered Python code is captured from Houdini
- **AND** results are ranked from that capture

#### Scenario: Search live VEX code
- **WHEN** a VEX query is submitted
- **THEN** current registered VEX code is captured from Houdini
- **AND** results are ranked from that capture

#### Scenario: No code-bearing nodes match
- **WHEN** capture succeeds but the selected language/scope has no matching code
- **THEN** Search succeeds with an empty logical result

### Requirement: Keep live Python/VEX indexing transient

Searchable live code and its dense/lexical index state SHALL be scoped to the search operation or another non-persistent runtime object.

#### Scenario: Live code search completes
- **WHEN** current node code has been searched
- **THEN** no durable live-code search namespace is required for a later call
- **AND** the next call recaptures current Houdini code

### Requirement: Support path scoping for live code search

Live Python/VEX capture SHALL support exact node-path scope, Houdini child-name glob scope, and optional recursive descendant inclusion.

#### Scenario: Restrict to exact node path
- **WHEN** path scope names one exact node and recursion is disabled
- **THEN** only that node is eligible for live code capture

#### Scenario: Restrict with child-name glob
- **WHEN** a Houdini child-name glob is supplied
- **THEN** matching children are selected using Houdini selection semantics

#### Scenario: Recursive scope is requested
- **WHEN** recursion is enabled for selected nodes
- **THEN** descendants below those selected nodes are eligible

### Requirement: Support semantic like-node live-code search

Live Python/VEX search SHALL support using code from one exact node path as the dense embedding query. The source node itself SHALL not be returned as the trivial nearest match to its own source.

#### Scenario: Search like one Python node
- **WHEN** a valid Python source node is selected as the semantic query
- **THEN** its current code embedding is used as the dense query
- **AND** the source entry is excluded from returned candidates

#### Scenario: Query mode is ambiguous
- **WHEN** both a text query and a like-node query are supplied, or neither is supplied
- **THEN** live-code search rejects the request before scanning

### Requirement: Preserve live code bodies as Resources rather than inline hit text

For live Python/VEX search, matching code bodies SHALL be materialized as Resources. Public search hit data SHALL refer to the code Resource rather than duplicating the complete source inline.

#### Scenario: A live code hit is returned
- **WHEN** one current node matches
- **THEN** the exact captured code body is available through its Resource
- **AND** the hit itself does not need to inline the source body

### Requirement: Search current Houdini node instances

Node search SHALL scan current live scene node instances. Matching SHALL be case-insensitive against the node's own `name`, node `type`, and type `category`; it SHALL not produce a match solely because an ancestor path segment contains the query. Results SHALL be ranked by match class in this order: exact field match, field-prefix match, field-substring match. Ties SHALL be ordered by node path using case-insensitive lexical order. Node search SHALL expose this ordering through result order and SHALL NOT manufacture a numeric relevance score.

#### Scenario: Search all current scene nodes
- **WHEN** no path scope is provided
- **THEN** current live nodes are searched and ordered by exact, prefix, then substring match class up to the requested limit

#### Scenario: Ancestor name contains the query
- **WHEN** a node's own searchable name/type/category does not match but an ancestor path segment does
- **THEN** the node is not returned solely because of that ancestor text

### Requirement: Support path scoping for live node search

Live node search SHALL support exact path, child-name glob, and optional recursive descendant selection.

#### Scenario: Scope node search to a path
- **WHEN** an exact path is supplied without recursion
- **THEN** the selected node is searched without implicitly scanning all descendants

#### Scenario: Scope by direct-child glob
- **WHEN** a child-name glob is supplied
- **THEN** matching direct children are selected

#### Scenario: Include descendants
- **WHEN** recursion is enabled
- **THEN** descendants of selected nodes are included

### Requirement: Route oversized live node results through common Output

Live node search SHALL return its complete logical result to the shared Output subsystem. Search code SHALL not implement a separate output-size policy.

#### Scenario: A scene produces many node hits
- **WHEN** the logical result exceeds the common inline budget
- **THEN** common Output performs Resource fallback

### Requirement: Use the current `.houbridge/python` workspace for script search

Workspace script search SHALL recursively index Python files below `<cwd>/.houbridge/python` and SHALL use `<cwd>/.houbridge/search.db` for its local derived database state.

#### Scenario: Search from one working directory
- **WHEN** the current directory changes to another workspace
- **THEN** script search uses that workspace's `.houbridge/python` tree and `.houbridge/search.db`

### Requirement: Use the Python module docstring as the script description

For valid Python source, workspace script search SHALL statically extract the module docstring without executing the file. A non-empty module docstring SHALL be treated as file-level `description` metadata and SHALL participate in semantic script ranking together with that file's source text. The original Python file SHALL remain authoritative for the description.

A file without a module docstring SHALL remain fully searchable and SHALL have no fabricated description. A Python file that cannot be parsed as an AST SHALL likewise receive no inferred description.

#### Scenario: Script declares a module docstring
- **WHEN** a valid Python file has a non-empty module docstring
- **THEN** the normalized module docstring is retained as that file's `description` metadata
- **AND** the description contributes to the dense searchable representation for that file
- **AND** the file is not executed to obtain the description

#### Scenario: Script has no module docstring
- **WHEN** a valid Python file has no non-empty module docstring
- **THEN** the file remains searchable from its source representation
- **AND** no description is fabricated

#### Scenario: Script is temporarily invalid Python
- **WHEN** AST parsing fails but the file remains searchable as a file document
- **THEN** no module description is inferred from comments or arbitrary string literals

### Requirement: Keep searchable script source authoritative in files

Workspace script search SHALL persist metadata, content hashes, contentless lexical structures when used, embedding vectors/cache, and other derived indexing state without treating database text as the authoritative source body.

#### Scenario: Inspect script-search database storage
- **WHEN** a script has been indexed
- **THEN** the database can identify and rank current file-level entries
- **AND** the original file remains the authoritative searchable source

### Requirement: Keep the script index current automatically

Before serving workspace script results, Script Search SHALL scan the current `.houbridge/python` tree and reconcile its file-level namespace. A newly discovered Python file SHALL be indexed automatically; a changed file SHALL replace its previous derived entry; a file no longer present in the current tree SHALL be removed from the searchable namespace before results are returned. A public rebuild command SHALL not be required for ordinary use.

#### Scenario: A Python file is added
- **WHEN** a previously unindexed Python file exists in the current `.houbridge/python` tree
- **THEN** it is indexed before current search results are served

#### Scenario: A Python file changes
- **WHEN** its current content hash differs from the indexed file entry
- **THEN** the stale derived entry is replaced before search results are served

#### Scenario: An indexed Python file was removed
- **WHEN** the indexed path no longer exists in the current `.houbridge/python` tree
- **THEN** that stale file entry is excluded/removed before search results are served

#### Scenario: Index is already current
- **WHEN** current file paths/content hashes and embedding profile match the indexed namespace
- **THEN** script search reuses the existing derived state

### Requirement: Index one semantic document per Python file

Workspace script search SHALL index at most one public retrieval document per Python file. The searchable representation SHALL be derived from the file's decoded Python source together with its optional normalized module description. Function, class, nested-symbol, qualified-name, and line-range fragments SHALL NOT become independently ranked script-search entries.

#### Scenario: File contains many functions and classes
- **WHEN** one Python file contains multiple definitions
- **THEN** Script Search creates one file-level retrieval entry
- **AND** one query can return that path at most once

#### Scenario: Python source is temporarily invalid
- **WHEN** source decoding succeeds but AST parsing fails
- **THEN** the non-empty file remains searchable as one file-level document
- **AND** no fabricated module description is added

### Requirement: Respect declared Python source encodings

Workspace script reading SHALL use Python's declared source-encoding rules.

#### Scenario: Python file declares a supported encoding
- **WHEN** `tokenize.open`-compatible encoding metadata is present
- **THEN** the file is decoded using Python's source encoding rules before building its file-level searchable representation

### Requirement: Search workspace scripts by embedding similarity

Workspace script query mode SHALL use the configured code embedding profile and dense cosine similarity over current file-level entries. An empty index SHALL return an empty logical result without attempting an invalid dense query.

#### Scenario: Search current scripts
- **WHEN** current file-level script entries exist
- **THEN** the query is embedded with the configured profile and ranked by dense similarity

#### Scenario: Workspace has no indexed entries
- **WHEN** `.houbridge/python` is missing or contains no indexable Python files
- **THEN** script search succeeds with no hits

### Requirement: Disable workspace script indexing as one feature unit

Effective `[local_script_database].enabled = false` SHALL disable workspace script index creation and refresh.

#### Scenario: Feature is disabled
- **WHEN** workspace script search is invoked
- **THEN** no `.houbridge/search.db` is created as a side effect
- **AND** the feature reports that the local script database is disabled

### Requirement: Provide shared dense and hybrid search primitives

The shared search layer SHALL support Model2Vec-compatible embeddings, sqlite-vec cosine KNN, SQLite FTS5/BM25 where lexical ranking is used, reciprocal-rank fusion for hybrid paths, embedding caching, and namespace/filter support. Dense-only operations MAY use only the dense branch.

#### Scenario: Hybrid live-code search runs
- **WHEN** a live-code operation requests both lexical and dense rankings
- **THEN** rankings are fused by reciprocal-rank fusion rather than by combining incomparable raw score magnitudes

#### Scenario: Session Action History performs hybrid recall
- **WHEN** History supplies lexical and executed-source dense rankings
- **THEN** it may reuse the same low-level RRF primitive without becoming part of workspace script-search persistence

#### Scenario: Dense vectors already exist for a content/profile pair
- **WHEN** the same embedding is required again inside a persistence scope that permits caching
- **THEN** the reusable embedding cache may avoid recomputation

### Requirement: Keep multiple embedding profiles separable

Derived search storage SHALL distinguish embedding profile identity so vectors created under one code embedding profile are not silently interpreted as another profile.

#### Scenario: Embedding profile changes
- **WHEN** the effective workspace script code profile changes from the profile used by existing file entries
- **THEN** Script Search refreshes/re-embeds the affected current file entries before serving results under the new profile
- **AND** profile identity remains explicit
- **AND** queries consume only compatible vectors unless a feature explicitly spans profiles

### Requirement: Normalize every public Search score through one shared formatter

All public retrieval `score` values produced by Search features or History search SHALL be produced by one shared Search score-formatting function. Feature-specific result builders SHALL NOT directly multiply or round public scores.

The shared formatter SHALL apply metric-specific public scaling before rounding:

- dense cosine similarity: `raw_score * 1000`,
- reciprocal-rank-fusion score: `raw_score * 10000`.

The public serialized score SHALL remain a JSON number and SHALL contain exactly six fractional decimal digits, for example `301.278910` or `317.540323`. The integer part SHALL not be padded; its width follows the calculated value.

#### Scenario: Format a dense cosine score
- **WHEN** the internal dense score is `0.30127891`
- **THEN** the public score is serialized as `301.278910`

#### Scenario: Format a reciprocal-rank-fusion score
- **WHEN** the internal RRF score is approximately `0.0317540323`
- **THEN** the public score is serialized as `317.540323`

#### Scenario: A retrieval feature emits results
- **WHEN** live code search, workspace script search, or History search exposes a public score
- **THEN** the score passes through the shared formatter
- **AND** the feature does not implement a local public multiplier or rounding rule
- **AND** live node search does not emit a public score because its command contract defines no score field

### Requirement: Keep injected live-search capture code under the Search script boundary

Houdini-side node scanning and code extraction source used by live Search SHALL reside below `houbridge/houdini/scripts/search/` or focused shared Houdini query modules.

#### Scenario: Live Python/VEX capture runs
- **WHEN** Search needs current code-bearing node data from Houdini
- **THEN** reusable capture source comes from the Search injected-script boundary
