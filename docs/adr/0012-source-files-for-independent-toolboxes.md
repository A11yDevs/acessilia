# 0012. Send source files to independent Toolbox deployments

- **Status:** Accepted
- **Date:** 2026-10-26
- **Components:** core; existing SDK and Toolbox transports unchanged
- **Reference:** [PR #309](https://github.com/A11yDevs/acessilia/pull/309)

## Context

Upload and structure extraction select endpoints independently. An artifact
uploaded to one independent deployment is not necessarily available at another.
ADR-0006 reserves multiple URLs for independent deployments; a single URL may
address replicas sharing central storage. The SDK already supports direct file
input, while artifact resend after a 404 is deliberately disabled by default.

## Decision

For initial structure extraction, the core sends the source file directly when
its configured extraction/upload clients span multiple distinct endpoint URLs.
It does not perform the separate artifact upload, even when artifact-store use
was requested. A single deployment retains reference-based input when enabled,
as described by ADR-0005. An explicitly different secondary deployment receives
the source file rather than the primary deployment's artifact ID.

This is an initial-input transport policy, not automatic re-upload after a
missing-artifact response. SDK resend defaults, retries, catalogue checks,
provider choice, capability schemas and output-artifact routing are unchanged.
No extraction executor is moved into the core.

## Consequences

Each direct extraction attempt/provider may transfer the source again. The
initial source artifact ID is unset for multi-endpoint extraction, and the
reported `use_artifact_store` configuration reflects actual use. The source
file must remain available until the extraction calls finish. Output artifacts
and later processing stages still need their own routing guarantees (ADR-0013).

The policy logs when artifact storage is bypassed despite being enabled.
Fusion and text-span calls may then send the full source again. Before rollout,
operators must check the deployed `TOOLBOX_BASE_URLS` in staging and production,
confirm whether URLs are independent deployments or replicas behind one shared
storage endpoint, and exercise representative large PDFs in staging. The empty
value in `.env.example` does not establish the deployed topology.

Tests reproduce the independent-client selection failure and verify normal and
failed-primary direct input, no upload-client creation, single-endpoint
reference compatibility, and a secondary provider on a different deployment.
No dataset evaluation or production deployment is part of this decision.
