# Resource Feature Specification

## Purpose

Define workspace-local, content-addressed Resources used for large or inspectable payloads. Command JSON schemas are specified separately.

## Requirements

### Requirement: Keep Resources self-contained

Resources SHALL be self-contained workspace inspection artifacts. Resource lookup, reading, slicing, search, and semantic alias resolution SHALL depend only on Resource persistence and generic configuration.

#### Scenario: Reopen a workspace Resource
- **WHEN** a Resource id from `<cwd>/.houbridge/resources.db` is inspected later
- **THEN** Resource resolves it from the Resource database without requiring another feature database

### Requirement: Store all Resource state in one workspace database

Resource payload bytes, metadata, canonical identities, semantic aliases, and semantic tag registry SHALL be stored in `<current-working-directory>/.houbridge/resources.db`. The implementation SHALL NOT create `.houbridge/resources/` or another Resource payload-file tree.

#### Scenario: Store a binary Resource
- **WHEN** arbitrary bytes are stored
- **THEN** the exact bytes are persisted as database payload data
- **AND** the Resource can be read without resolving a filesystem payload path

#### Scenario: Store a text or JSON Resource
- **WHEN** content is classified as UTF-8 text or JSON
- **THEN** the exact payload bytes, content class, MIME type, byte size, and estimated token count are persisted in the same Resource database

#### Scenario: Delete local Resource storage
- **WHEN** `.houbridge/resources.db` is deleted
- **THEN** previously returned local Resource references from that database may stop resolving
- **AND** other feature stores remain independent

### Requirement: Classify Resource content from exact payload bytes

Resource SHALL use one shared content classifier when payload bytes are stored. Classification SHALL proceed in this order:

1. inspect the payload with the `filetype` package; when a recognized binary file signature is found, classify the Resource as `binary` and use the detected MIME type,
2. otherwise require strict UTF-8 decoding; undecodable payloads or payloads containing binary control characteristics such as NUL SHALL be classified as `binary` with `application/octet-stream` when no more specific MIME is known,
3. for valid text, attempt JSON parsing; valid JSON SHALL be classified as `json` with MIME `application/json`,
4. remaining valid UTF-8 content SHALL be classified as `text` with MIME `text/plain`.

The resulting content class and MIME SHALL be the common basis for Resource info, get, search, slice, semantic tagging, and dump behavior. Feature-specific MIME whitelists SHALL NOT independently redefine text/binary classification.

#### Scenario: PNG bytes are stored
- **WHEN** `filetype` recognizes the PNG signature
- **THEN** the Resource is classified as `binary`
- **AND** its MIME is `image/png`

#### Scenario: Unknown bytes are not valid UTF-8
- **WHEN** `filetype` does not recognize the payload and strict UTF-8 decoding fails
- **THEN** the Resource is classified as `binary`
- **AND** its MIME falls back to `application/octet-stream`

#### Scenario: UTF-8 payload contains valid JSON
- **WHEN** strict UTF-8 decoding succeeds and JSON parsing succeeds
- **THEN** the Resource is classified as `json`
- **AND** its MIME is `application/json`

#### Scenario: UTF-8 payload is not JSON
- **WHEN** strict UTF-8 decoding succeeds and JSON parsing fails
- **THEN** the Resource is classified as `text`
- **AND** its MIME is `text/plain`

### Requirement: Use SHA-256 as canonical Resource identity

The lowercase SHA-256 hash of exact payload bytes SHALL be the canonical Resource identity. Identical payload bytes SHALL deduplicate to one canonical Resource regardless of which feature stored them.

#### Scenario: Store duplicate content
- **WHEN** identical bytes are written more than once
- **THEN** all writes resolve to the same canonical SHA-256 identity
- **AND** only one canonical payload is required in the Resource database

### Requirement: Expose stable semantic Resource aliases

Public Resource references SHALL use a stable semantic alias registered over the canonical SHA-256 identity. The same canonical Resource SHALL keep the same semantic alias once assigned. Resource lookup SHALL accept both the semantic alias and the canonical SHA-256 identity.

#### Scenario: Resolve a semantic Resource id
- **WHEN** a previously returned semantic Resource id is supplied
- **THEN** it resolves to the registered canonical SHA-256 Resource

#### Scenario: Resolve a canonical SHA-256 id
- **WHEN** a valid existing canonical Resource hash is supplied
- **THEN** it resolves directly
- **AND** the Resource's registered semantic alias remains available

### Requirement: Generate semantic aliases from three Potion tags

Semantic tag extraction SHALL use `minishlab/potion-code-16M-v2`. Tag generation SHALL:

- embed Resource semantic text with the Potion model,
- choose the highest-ranked usable vocabulary atom as representative,
- form its alias group from usable vocabulary atoms whose cosine similarity to that representative is at least `0.35`,
- rank that group by similarity to the Resource embedding,
- select three distinct usable normalized tags,
- join the three tags with `-`, and
- append a decimal ordinal local to that exact three-tag prefix.

The ordinal SHALL have a minimum width of three digits (`000`, `001`, ...); values beyond three digits SHALL expand naturally rather than wrapping or changing the prefix.

#### Scenario: First Resource for a semantic prefix
- **WHEN** three selected tags are `node`, `graph`, and `python`
- **AND** the prefix has no prior Resource
- **THEN** the semantic id uses prefix `node-graph-python` with ordinal `000`

#### Scenario: Prefix exceeds 999 Resources
- **WHEN** the next prefix-local ordinal is 1000
- **THEN** the semantic id ends in `1000`
- **AND** no existing ordinal is reused

#### Scenario: Resource embedding is zero length
- **WHEN** Potion produces the defined zero-embedding failure
- **THEN** semantic tagging falls back to `resource`, `unknown`, `content`
- **AND** other semantic-id failures are not silently hidden by that fallback

### Requirement: Filter unusable semantic tag atoms

Semantic tags SHALL exclude tokenizer continuations, empty tokens, numeric-only literals, non-ASCII/control tokens, tokens without alphabetic content, and other normalized tokens that cannot produce a stable readable id. Three distinct usable tags are required for normal semantic-id generation.

#### Scenario: Alias group contains duplicate normalized tags
- **WHEN** different vocabulary atoms normalize to the same tag
- **THEN** only the first ranked normalized tag is retained
- **AND** selection continues until three distinct usable tags are obtained or generation fails

### Requirement: Derive semantic text deterministically from classified Resource content

`text` and `json` Resources SHALL use their decoded UTF-8 content as semantic text. A `binary` Resource SHALL use its MIME string when available, otherwise `resource`; binary payload bytes SHALL NOT be decoded with replacement solely to manufacture semantic text. Blank decoded text SHALL likewise fall back to MIME when available, otherwise `resource`.

#### Scenario: Store binary bytes
- **WHEN** a Resource is classified as `binary`
- **THEN** semantic tagging uses MIME or `resource` as the semantic text source
- **AND** arbitrary binary bytes are not interpreted as replacement-decoded text

### Requirement: Keep Resource metadata minimal

Resource persistence SHALL contain content-inspection metadata needed by the Resource feature: canonical identity, content class, MIME type, byte size, estimated token count when applicable, creation metadata, payload, semantic alias, and semantic tag/ordinal registry. Feature-specific caller context SHALL remain with the caller rather than being copied into generic Resource metadata.

#### Scenario: Execution stores a result Resource
- **WHEN** Execution materializes a result
- **THEN** Resource persistence does not duplicate Execution-specific provenance beyond the generic Resource fields

### Requirement: Materialize execution output as Resources

Execution result, stdout, stderr, and exception/traceback payloads SHALL be storable as Resources. Small text/JSON may additionally be presented inline according to the common Output Policy without changing Resource persistence.

#### Scenario: Small execution result
- **WHEN** a small result is also allowed inline
- **THEN** its Resource still exists when the owning feature requires a Resource reference

#### Scenario: Large execution result
- **WHEN** the common Output Policy does not allow the body inline
- **THEN** the complete artifact remains available as a Resource

### Requirement: Materialize Resource payloads as temporary files

Resource SHALL support materializing the exact stored payload bytes as a completed file in the shared Houbridge temporary-artifact area. Resource SHALL derive the preferred filename extension from the stored MIME using Python's standard `mimetypes.guess_extension()`. When no extension can be inferred, `.bin` SHALL be used. Dumping SHALL NOT re-encode text/JSON or otherwise transform the stored payload.

#### Scenario: Dump a PNG Resource
- **WHEN** a Resource has MIME `image/png`
- **THEN** its exact stored bytes are published through the shared temporary-artifact boundary
- **AND** the resulting path uses the `.png` extension when inferred by `mimetypes`

#### Scenario: Dump a MIME with no known extension
- **WHEN** `mimetypes.guess_extension()` returns no extension
- **THEN** the temporary artifact uses `.bin`

#### Scenario: Dump JSON Resource
- **WHEN** an `application/json` Resource is dumped
- **THEN** the file contains the exact stored payload bytes
- **AND** the dump path uses the MIME-derived extension rather than reserializing JSON

### Requirement: Support bounded full Resource inspection

Resource inspection SHALL use the persisted `text`, `json`, and `binary` content classes. A normal full read SHALL respect the configured Resource inline byte threshold, while an explicit full-read request MAY bypass only that soft inspection threshold and SHALL NOT bypass the fixed CLI hard emission boundary.

#### Scenario: Read a small text Resource
- **WHEN** the payload is within the configured Resource read threshold and fixed hard output boundary
- **THEN** the complete decoded text can be returned by Resource inspection

#### Scenario: Read JSON
- **WHEN** an `application/json` Resource contains valid JSON within the permitted read budget
- **THEN** Resource inspection decodes it as JSON data

#### Scenario: Inspect binary content
- **WHEN** a Resource is classified as `binary`
- **THEN** full text decoding is not attempted
- **AND** bounded metadata inspection remains available

#### Scenario: Full read exceeds hard output boundary
- **WHEN** text exceeds 65536 bytes
- **THEN** a full read does not inline the body even when the soft threshold is explicitly bypassed
- **AND** bounded slicing remains available

### Requirement: Support bounded UTF-8 slicing

`text` and `json` Resources SHALL support offset/limit slicing. Offset SHALL be non-negative and limit positive. One slice SHALL request and return at most 16384 UTF-8 bytes. When a requested character range would encode above the byte maximum, the result SHALL end at a valid UTF-8 boundary.

#### Scenario: Slice a large text Resource
- **WHEN** a bounded slice is requested
- **THEN** only that bounded region is decoded and returned
- **AND** inspection can indicate that additional content remains for continuation

#### Scenario: Slice contains multibyte text
- **WHEN** the selected character region would encode above 16384 bytes
- **THEN** the returned prefix is shortened without emitting invalid UTF-8

### Requirement: Support bounded Resource text search

`text` and `json` Resources SHALL support case-insensitive literal substring search without loading the whole Resource into public command output. Search shall support a zero-based result offset, use the configured per-call search result limit, and never return more than 100 hits in one operation.

#### Scenario: Search text content
- **WHEN** a query occurs multiple times in a text Resource
- **THEN** Resource search finds all logical matches for hit counting
- **AND** returns only the requested bounded hit window
- **AND** match offsets are character offsets suitable for later text slicing

#### Scenario: Search multibyte text
- **WHEN** matches occur after multibyte UTF-8 characters
- **THEN** offsets remain character offsets rather than raw UTF-8 byte positions

### Requirement: Provide structural context for JSON search hits

Searching `application/json` SHALL associate a match with the narrowest containing JSON value. The feature SHALL be able to identify the JSON path, source character offset, and estimated token count of that complete containing value. A match in an object key SHALL map to that key's value path.

#### Scenario: Match inside a JSON value
- **WHEN** a query occurs in a nested JSON value
- **THEN** the hit identifies the corresponding JSON path
- **AND** token cost is estimated for the complete value at that path

#### Scenario: Match occurs in an object key
- **WHEN** a query matches an object key
- **THEN** the hit is associated with the value addressed by that key's path

### Requirement: Reject invalid Resource inspection operations

Resource inspection SHALL fail explicitly for unknown Resource aliases, invalid ids, invalid JSON when JSON structural inspection is required, invalid slice/search offsets, empty search queries, and text-only operations requested against binary Resources.

#### Scenario: Unknown semantic alias
- **WHEN** a semantic Resource id is not registered
- **THEN** Resource resolution reports not found

#### Scenario: Search binary Resource
- **WHEN** text search is requested for a `binary` Resource
- **THEN** the operation is rejected as unavailable for that content class
