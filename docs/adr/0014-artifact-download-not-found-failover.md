# 0014. Search compatible endpoints for a missing artifact download

- **Status:** Accepted
- **Date:** 2026-10-26
- **Components:** SDK

## Context

An independent deployment can lack an artifact that another deployment stores.
The general 4xx policy in ADR-0006 stops on the first missing-object response.

The affected consumer is the SDK's public `ToolboxArtifactClient.download`
interface, intended for SDK callers retrieving an artifact by ID. The Core
does not currently call that method: its capability clients fetch their
outputs through the producing endpoint instead. This change therefore fixes
the public SDK contract, not an existing Core download call site.

## Decision

For artifact downloads by ID only, a 404 advances to the next compatible
endpoint without retrying that same missing object on the same endpoint.
All-404 attempts remain `ToolboxArtifactNotFound`. Mixed availability failures
retain the existing combined errors. Other operations and 4xx codes are unchanged.

In particular, 404 followed by a timeout raises `ToolboxUnavailable`, with
both causes retained. It does not prove the artifact is absent everywhere;
the second endpoint could not answer. It must not trigger a not-found-only
re-upload policy. Tests cover this mixed case, all-404, and corrupt downloads.

## Consequences

Missing downloads may require more requests. Hash/signature checks and atomic
file replacement remain mandatory; corrupt success responses do not trigger
failover. This scoped exception to ADR-0006 does not enable file re-upload.
