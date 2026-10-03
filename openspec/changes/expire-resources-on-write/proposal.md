# Expire Resources on Successful Writes

## Why

Expired Resource payloads currently may remain active until lazy cleanup runs. Removing expired payloads during a successful write gives writes a defined cleanup point while preserving the existing 72-hour, latest-write retention policy.

## What Changes

- Each successful Resource write removes payloads whose `expires_at` is less than or equal to that write's recorded time.
- Cleanup and the write's payload, identity, alias/ordinal, and retention updates commit atomically in the existing write transaction.
- Reads do not trigger cleanup or extend retention; no periodic cleanup task is added.

## Specification Impact

This modifies the Resource retention requirement only. It does not change Resource identity, aliases, ordinals, configuration, dump behavior, or public APIs.

## Scope

In scope:

- next-successful-write cleanup using the write's recorded timestamp,
- atomicity between cleanup and the current write/refresh,
- specification and implementation regression coverage for the boundary and rollback behavior.

Out of scope:

- periodic or background cleanup,
- cleanup on reads,
- schema, API, or migration changes,
- changes to alias/ordinal retention or dump semantics.
