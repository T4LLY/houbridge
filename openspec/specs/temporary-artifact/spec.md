# Temporary Artifact Specification

## Purpose

Define the shared mechanism for publishing completed command-generated files below the operating-system temporary directory without duplicating temp-path, collision, or atomic-publication logic across features.

## Requirements

### Requirement: Publish through one managed temporary boundary

Capture, Resource dump, and any later feature that returns a generated temporary file SHALL use one shared temporary-artifact publication service. The service SHALL resolve the operating-system temporary root, create Houbridge-managed namespace directories below it, reserve collision-safe final paths, and return the completed final path.

#### Scenario: Two artifacts request the same readable stem
- **WHEN** two publications would otherwise select the same filename
- **THEN** the shared service reserves distinct final paths
- **AND** neither publication overwrites the other implicitly

### Requirement: Publish exact completed bytes atomically

The shared service SHALL accept exact bytes or a completed source file plus caller-supplied naming information. The final returned path SHALL not become a successful public artifact until its complete payload has been published. Publication SHALL preserve exact bytes and SHALL not perform MIME detection, text encoding, JSON serialization, image encoding, or video encoding.

#### Scenario: Resource publishes stored bytes
- **WHEN** Resource supplies a payload and `.png` extension
- **THEN** the final file contains byte-for-byte identical content
- **AND** the temporary service does not inspect or transform the payload format

#### Scenario: Producer fails before finalization
- **WHEN** publication does not complete successfully
- **THEN** no incomplete final path is returned as a successful artifact

### Requirement: Keep format classification with the producing feature

The temporary-artifact service SHALL not infer MIME or extension. Resource SHALL classify payload content and derive its dump extension before publication; Capture SHALL supply its known encoder output extension directly.

#### Scenario: Resource MIME has a known extension
- **WHEN** Resource resolves `image/png` to `.png`
- **THEN** the shared service publishes using the supplied `.png` extension

#### Scenario: Capture encodes MP4
- **WHEN** Capture completes MP4 encoding
- **THEN** Capture supplies `.mp4` directly
- **AND** the shared service does not re-detect the file type

### Requirement: Keep cleanup mechanics shared and retention policy external

The shared service MAY provide cleanup primitives limited to Houbridge-managed temporary namespaces. A caller's retention duration and cleanup trigger SHALL remain defined by that feature's configuration/specification rather than being hard-coded into the temporary-artifact service.

#### Scenario: Capture performs lazy retention cleanup
- **WHEN** Capture invokes cleanup according to its configured retention
- **THEN** shared cleanup mechanics operate only on Houbridge-managed temporary artifacts selected by Capture's policy
- **AND** files moved outside the managed namespace are not followed or deleted
