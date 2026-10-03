## MODIFIED Requirements

### Requirement: Retain active Resources for 72 hours from the latest write

Resource retention SHALL use the global-only `[resource].ttl_hours`; the generated default SHALL be `72` hours. Storing payload bytes SHALL establish or refresh the active Resource retention deadline from that write's recorded time. Re-storing identical bytes SHALL continue to deduplicate to the same canonical Resource while refreshing its active retention window. Resource reads SHALL NOT extend retention.

Each successful Resource write SHALL remove payloads and active inspection metadata for Resources whose `expires_at` is less than or equal to that write's recorded time. This cleanup and the write's payload, canonical identity, semantic alias/ordinal state, and retention refresh SHALL commit in the same existing write transaction. If that transaction fails, neither cleanup nor the write/refresh SHALL commit. A newly written or refreshed Resource SHALL remain active after cleanup. Expired payloads MAY remain until a subsequent successful Resource write; reads SHALL NOT trigger cleanup. No periodic cleanup task is required.

Semantic alias/canonical mapping and prefix ordinal reservation needed to preserve alias stability and prevent ordinal reuse SHALL survive ordinary TTL cleanup. A `resource dump` creates a temporary materialized copy; long-term preservation requires the caller to copy or move that dump outside Houbridge-managed temporary storage before its dump retention expires.

#### Scenario: Identical payload is written again
- **WHEN** an active canonical Resource is written again before expiry
- **THEN** no duplicate payload is required
- **AND** its active retention deadline is refreshed from the new write time

#### Scenario: Expired payload is stored again
- **WHEN** payload bytes were removed by TTL cleanup and the exact canonical bytes are later stored again
- **THEN** the existing canonical-to-semantic alias mapping is reused
- **AND** the payload becomes active for a new retention window

#### Scenario: Successful write cleans payloads expired at its recorded time
- **WHEN** a Resource write succeeds at recorded time `T`
- **AND** another active Resource has `expires_at` equal to or earlier than `T`
- **THEN** the expired payload and active inspection metadata are removed in that write transaction
- **AND** Resources with `expires_at` later than `T` remain active
- **AND** the newly written or refreshed Resource remains active
- **AND** semantic alias mappings and reserved ordinals remain available

#### Scenario: Failed write rolls back cleanup and the attempted write
- **WHEN** a Resource write transaction removes expired payloads but fails before commit
- **THEN** the expired payloads remain active
- **AND** the attempted payload, identity, alias/ordinal, and retention changes are not committed

#### Scenario: Expired payload awaits a successful write
- **WHEN** a Resource expires and no successful Resource write occurs
- **THEN** its payload MAY remain until a later successful write
- **AND** reading the Resource does not trigger cleanup or extend its retention

#### Scenario: Resource is read repeatedly
- **WHEN** `resource get` or another inspection command reads an existing Resource
- **THEN** the read does not extend its configured retention duration

#### Scenario: Reading does not trigger cleanup
- **WHEN** a read inspects a Resource whose retention deadline has passed
- **THEN** the read does not trigger cleanup
- **AND** its payload MAY remain until a later successful Resource write

#### Scenario: Resource alias expires from active storage
- **WHEN** ordinary TTL cleanup removes an expired payload
- **THEN** its semantic ordinal is not made available for a different canonical Resource
