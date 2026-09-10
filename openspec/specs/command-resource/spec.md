# Resource Command Specification

## Purpose

Define syntax, options, bounded inspection semantics, temporary dump behavior, and JSON responses for Resource metadata/read/search/slice/dump operations.

## Requirements


### Requirement: Select the global Resource store explicitly when requested

`resource info`, `resource get`, `resource search`, `resource slice`, and `resource dump` SHALL all accept `--root ROOT` with the common operational-root meaning. When omitted, Resource lookup SHALL use the configured global operational root. When supplied, Resource lookup SHALL use `<ROOT>/resources.db` without changing process cwd.

#### Scenario: Inspect a Resource from another working directory
- **WHEN** a Resource was created by a command in another cwd using the same global operational root
- **THEN** `houbridge resource get RESOURCE_ID` resolves it from the shared global `resources.db`

#### Scenario: Explicit root is supplied
- **WHEN** `houbridge resource get RESOURCE_ID --root E:/houbridge-state` is invoked
- **THEN** Resource lookup uses `E:/houbridge-state/resources.db`
- **AND** the caller's process working directory is unchanged

### Requirement: Expose Resource metadata inspection

The syntax SHALL be:

```text
houbridge resource info RESOURCE_ID [--root ROOT]
```

`RESOURCE_ID` is a required semantic alias or canonical SHA-256 Resource id.

Success SHALL report MIME together with exactly one size measure selected by the Resource subsystem's shared content classification. `text` and `json` classes SHALL use token count; `binary` SHALL use byte count.

A `text` or `json` Resource SHALL use:

```json
{
  "mime": "application/json",
  "tokens": 256
}
```

A `binary` Resource SHALL use:

```json
{
  "mime": "application/octet-stream",
  "bytes": 1234
}
```

`mime` SHALL be the classifier-resolved MIME string. `tokens` SHALL be present only for `text`/`json` Resources. `bytes` SHALL be present only for `binary` Resources. The supplied Resource id and canonical hash SHALL NOT be repeated in this minimal metadata response.

#### Scenario: Inspect text Resource metadata
- **WHEN** a Resource is classified as `text` or `json`
- **THEN** `tokens` reports its estimated token count
- **AND** `bytes` is omitted

#### Scenario: Inspect binary Resource metadata
- **WHEN** a Resource is classified as `binary`
- **THEN** `bytes` reports the payload byte size
- **AND** `tokens` is omitted

### Requirement: Expose Resource dump to managed temporary storage

The syntax SHALL be:

```text
houbridge resource dump RESOURCE_ID [--root ROOT]
```

`RESOURCE_ID` is a required semantic alias or canonical SHA-256 Resource id. The command SHALL read the exact stored payload bytes, derive an extension from the stored MIME with `mimetypes.guess_extension()`, fall back to `.bin` when no extension is available, and publish the completed file through the shared temporary-artifact boundary.

Success SHALL contain exactly:

```json
{"path":"D:/Temp/.../resource-....png"}
```

`dump` SHALL support `binary`, `text`, and `json` Resources. It SHALL NOT decode, reserialize, base64-encode, or otherwise transform the payload before publication.

#### Scenario: Dump a binary Resource
- **WHEN** `resource dump` resolves a Resource with MIME `image/png`
- **THEN** the exact payload bytes are written to a completed temporary `.png` file
- **AND** success returns only its `path`

#### Scenario: Dump an unknown MIME
- **WHEN** the stored MIME has no extension mapping
- **THEN** the published temporary filename ends in `.bin`

#### Scenario: Dump text or JSON
- **WHEN** a text or JSON Resource is dumped
- **THEN** its exact stored bytes are written without text normalization or JSON reserialization

### Requirement: Expose bounded Resource get

The syntax SHALL be:

```text
houbridge resource get RESOURCE_ID [--root ROOT] [--full]
```

`--full` MAY bypass only the configured soft Resource inline-read threshold. It SHALL NOT bypass the fixed 65536-byte CLI hard boundary.

Small text success SHALL be:

```json
{"truncated":false,"result":"hello"}
```

Small JSON success SHALL decode the Resource as JSON:

```json
{"truncated":false,"result":{"foo":"bar"}}
```

A `text` or `json` Resource that is not returned because of the soft/hard read bound SHALL use:

```json
{"truncated":true,"next_offset":0}
```

A `binary` Resource SHALL use:

```json
{"truncated":false,"binary":true}
```

#### Scenario: Full read is requested below hard boundary
- **WHEN** a `text` or `json` Resource exceeds only the configured soft threshold
- **AND** `--full` is supplied
- **THEN** the complete body may be returned

#### Scenario: Resource exceeds hard boundary
- **WHEN** a `text` or `json` Resource exceeds 65536 bytes
- **THEN** `get` does not inline the body even with `--full`
- **AND** returns `truncated:true` and `next_offset:0`

### Requirement: Expose bounded Resource slicing

The syntax SHALL be:

```text
houbridge resource slice RESOURCE_ID [--root ROOT] --offset INTEGER --limit INTEGER
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
houbridge resource search RESOURCE_ID QUERY [--root ROOT] [--offset INTEGER]
```

`QUERY` is required and non-empty. `--offset` defaults to `0` and selects the zero-based hit offset. Search is case-insensitive literal substring search and one response SHALL expose no more than the configured bounded search limit and never more than 100 hits.

For `text` content, success SHALL use:

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

Resource inspection and dump commands SHALL use their explicit bounded or path-only responses rather than recursively Resource-fallbacking the inspected payload into another Resource. `resource get`, `resource search`, and `resource slice` SHALL keep their bounded continuation behavior; `resource dump` SHALL return only the temporary artifact path.

#### Scenario: Get is too large
- **WHEN** a Resource cannot be returned within the get boundary
- **THEN** `get` returns its `truncated` continuation response
- **AND** does not replace that response with a new Resource id

### Requirement: Use the shared error envelope for Resource failures

Unknown Resource ids, invalid aliases, invalid JSON structural inspection, binary text operations, empty queries, invalid offsets, invalid slice limits, and temporary dump publication failures SHALL use the common BridgeError JSON envelope.

#### Scenario: Resource does not exist
- **WHEN** `resource info missing-id` cannot resolve the id
- **THEN** the command exits with status `1`
- **AND** emits the common `error/code/message[/detail]` JSON shape
