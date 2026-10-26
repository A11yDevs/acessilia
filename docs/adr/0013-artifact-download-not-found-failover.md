# 0013. Search compatible endpoints for a missing artifact download

- **Status:** Accepted
- **Date:** 2026-10-26
- **Components:** SDK

## Context

An independent deployment can lack an artifact that another deployment stores.
The general 4xx policy in ADR-0006 stops on the first missing-object response.

## Decision

For artifact downloads by ID only, a 404 advances to the next compatible
endpoint without retrying that same missing object on the same endpoint.
All-404 attempts remain `ToolboxArtifactNotFound`. Mixed availability failures
retain the existing combined errors. Other operations and 4xx codes are unchanged.

## Consequences

Missing downloads may require more requests. Hash/signature checks and atomic
file replacement remain mandatory; corrupt success responses do not trigger
failover. This scoped exception to ADR-0006 does not enable file re-upload.
