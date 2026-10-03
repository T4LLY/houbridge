# Tasks

## 1. Specification

- [x] 1.1 Define cleanup of resources with `expires_at <=` the recorded time of each successful write.
- [x] 1.2 Define cleanup and payload/identity/alias/ordinal/retention updates as one atomic write transaction, including rollback behavior.
- [x] 1.3 Preserve latest-write TTL refresh, non-extending reads, lazy expiry without writes, alias/ordinal stability, and dump semantics.

## 2. Implementation

- [x] 2.1 Add next-write expiry cleanup inside the existing Resource write transaction using that write's recorded time.
- [x] 2.2 Sync the approved retention behavior into the canonical Resource specification.
- [x] 2.3 Add regression coverage for exact-expiry cleanup, non-expired payloads, refreshed payload/alias/ordinal retention, non-cleaning reads, and transaction rollback.

## 3. Verification

- [x] 3.1 Run the targeted Resource test suite.
- [x] 3.2 Validate this OpenSpec change in strict mode.
