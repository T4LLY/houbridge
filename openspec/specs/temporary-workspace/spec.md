# Temporary Workspace Specification

## Purpose

Define private invocation-local filesystem state used while managed Houdini Python execution is active or recoverable. Temporary Workspaces are transport/recovery state, not public generated artifacts.

## Requirements

### Requirement: Allocate private invocation workspaces in operating-system temporary storage

Execution and Task Runtime SHALL allocate collision-safe Houbridge-managed invocation directories below the operating-system temporary root. A workspace SHALL be associated with one managed invocation/Task attempt and MAY contain stdout/stderr transport buffers, started/completion markers, and other execution transport files required for recovery. Workspace paths SHALL remain private and SHALL not appear in public command success JSON.

#### Scenario: Async Task prepares invocation files
- **WHEN** Task Runtime prepares a caller Python invocation
- **THEN** its transport files are isolated in a private managed workspace
- **AND** they do not share mutable filenames with another invocation

### Requirement: Publish started and completion markers atomically

The started marker SHALL become visible only after the Houdini-side wrapper has established the invocation state needed to prove that caller Python may have started. The completion marker SHALL become visible only after the wrapper has captured the terminal Python outcome and flushed stdout/stderr transport streams. Marker publication SHALL be atomic so recovery never observes a partially written marker as valid.

#### Scenario: Runtime crashes during marker write
- **WHEN** a marker write is interrupted before atomic publication
- **THEN** recovery does not treat the partial marker as a valid started/completed state

### Requirement: Preserve active workspaces only while recovery may require them

Task Runtime SHALL retain an invocation workspace while a Task is queued/running or terminal finalization still depends on its buffers/markers. After terminal streams and outcome have been committed to authoritative Task/Resource state and recovery no longer requires the workspace, the workspace SHALL be removed. Stale workspace cleanup SHALL consult Task/runtime ownership rather than deleting active work solely by age.

#### Scenario: Task terminal state is committed
- **WHEN** authoritative Task output/outcome no longer requires invocation files
- **THEN** its private Temporary Workspace is removed

#### Scenario: Runtime dies during a running Task
- **WHEN** replacement runtime can recover the invocation from Task state and markers
- **THEN** stale cleanup does not delete that active workspace before recovery completes

### Requirement: Keep Temporary Workspace separate from Temporary Artifact

Temporary Workspace SHALL own unpublished execution transport/recovery files. Temporary Artifact SHALL own completed files intentionally returned to callers such as Capture output and Resource dumps. Neither subsystem SHALL silently assume the other's retention or publication semantics.

#### Scenario: Resource dump is returned to caller
- **WHEN** Resource publishes a dump path
- **THEN** it uses Temporary Artifact rather than Temporary Workspace
