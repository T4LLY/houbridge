# Resource Command Specification

## Purpose

Define syntax, options, bounded inspection semantics, and JSON responses for Resource metadata/read/search/slice operations.

## Requirements

### Requirement: Expose Resource metadata inspection

The syntax SHALL be:

```text
houbridge resource info RESOURCE_ID
```

`RESOURCE_ID` is a required semantic alias or canonical SHA-256 Resource id.

Success SHALL contain exactly:

```json
{
  "bytes": 1234,
  "mime": "application/json",
  "tokens": 256
}
```

`mime` and `tokens` MAY be `null`. The supplied Resource id and canonical hash SHALL NOT be repeated in this minimal metadata response.

#### Scenario: Inspect binary Resource metadata
- **WHEN** a binary Resource has no token estimate
- **THEN** `tokens` is `null`
- **AND** `bytes` still reports the payload byte size

### Requirement: Expose bounded Resource get

The syntax SHALL be:

```text
houbridge resource get RESOURCE_ID [--allow-full]
```

`--allow-full` MAY bypass only the configured soft Resource inline-read threshold. It SHALL NOT bypass the fixed 65536-byte CLI hard boundary.

Small text success SHALL be:

```json
{"truncated":false,"result":"hello"}
```

Small JSON success SHALL decode the Resource as JSON:

```json
{"truncated":false,"result":{"foo":"bar"}}
```

A text-like Resource that is not returned because of the soft/hard read bound SHALL use:

```json
{"truncated":true,"next_offset":0}
```

A non-text Resource SHALL use:

```json
{"truncated":false,"binary":true}
```

#### Scenario: Allow-full is requested below hard boundary
- **WHEN** a text Resource exceeds only the configured soft threshold
- **AND** `--allow-full` is supplied
- **THEN** the complete body may be returned

#### Scenario: Resource exceeds hard boundary
- **WHEN** a text Resource exceeds 65536 bytes
- **THEN** `get` does not inline the body even with `--allow-full`
- **AND** returns `truncated:true` and `next_offset:0`

### Requirement: Expose bounded Resource slicing

The syntax SHALL be:

```text
houbridge resource slice RESOURCE_ID --offset INTEGER --limit INTEGER
```

`--offset` is required and SHALL be at least `0`. `--limit` is required, SHALL be at least `1`, and SHALL NOT exceed `16384`.

A complete slice SHALL use:

```json
{"result":"partial text"}
```

When more characters remain after the returned chunk, success SHALL use:

```json
{
  "result": "partial text",
  "truncated": true,
  "next_offset": 1024
}
```

`next_offset` SHALL be the next character offset, not a raw UTF-8 byte position.

#### Scenario: Slice reaches end of Resource
- **WHEN** no content remains after the returned chunk
- **THEN** `truncated` and `next_offset` are omitted

#### Scenario: Limit exceeds hard slice maximum
- **WHEN** `--limit 16385` is requested
- **THEN** the command is rejected before returning Resource text

### Requirement: Expose bounded Resource literal search

The syntax SHALL be:

```text
houbridge resource search RESOURCE_ID QUERY [--offset INTEGER]
```

`QUERY` is required and non-empty. `--offset` defaults to `0` and selects the zero-based hit offset. Search is case-insensitive literal substring search and one response SHALL expose no more than the configured bounded search limit and never more than 100 hits.

For plain text-like content, success SHALL use:

```json
{
  "hit_count": 2,
  "hits": [
    {"offset":6},
    {"offset":17}
  ]
}
```

For JSON Resources, each hit SHALL identify structural context:

```json
{
  "hit_count": 2,
  "hits": [
    {"path":"$.nodes[0].name","offset":123,"tokens":8}
  ]
}
```

If additional hits exist beyond the returned window, `truncated:true` SHALL be added. `hit_count` SHALL remain the total logical match count, not merely the number returned in `hits`.

#### Scenario: More search hits remain
- **WHEN** the selected bounded window does not reach the final match
- **THEN** `truncated` is `true`

### Requirement: Keep Resource inspection out of recursive Resource fallback

`resource info`, `resource get`, `resource search`, and `resource slice` are themselves the bounded mechanism for inspecting oversized Resources. These commands SHALL use their explicit bounded responses and SHALL NOT recursively Resource-fallback their inspected body into another Resource merely because the body is large.

#### Scenario: Get is too large
- **WHEN** a Resource cannot be returned within the get boundary
- **THEN** `get` returns its `truncated` continuation response
- **AND** does not replace that response with a new Resource id

### Requirement: Use the shared error envelope for Resource failures

Unknown Resource ids, invalid aliases, invalid JSON structural inspection, binary text operations, empty queries, invalid offsets, and invalid slice limits SHALL use the common BridgeError JSON envelope.

#### Scenario: Resource does not exist
- **WHEN** `resource info missing-id` cannot resolve the id
- **THEN** the command exits with status `1`
- **AND** emits the common `error/code/message[/detail]` JSON shape
