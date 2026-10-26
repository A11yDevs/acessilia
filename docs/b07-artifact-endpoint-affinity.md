# B07 — Upload and extraction can select different Toolbox stores

## Brief description

The artifact-upload and structure-extraction clients choose endpoints
independently. With independent deployments, an upload can succeed on A while
extraction requests its ID on B, which does not have the object. B08's central
storage policy does not share artifacts between independent S3 deployments.

## Symptoms

- Upload succeeds, followed by extraction HTTP 404 on another endpoint.
- A's upload can fail over to B, while extraction restarts at A.
- A successful upload on A can be followed by extraction failover to B.
- Both cases work when all replicas actually share the same artifact store.

## Implemented solution

For multiple distinct endpoint URLs, the core sends the source file directly
with each initial extraction attempt and skips the separate artifact upload.
This applies even when `TOOLBOX_USE_ARTIFACT_STORE=true`. Explicitly different
upload/extraction clients also take the direct-file path. A single deployment
retains reference-based input when enabled; a secondary provider in another
deployment receives the source rather than the primary's artifact ID.

The reported `use_artifact_store` reflects actual use, and the source
`artifact_id` is unset when no separate upload occurs. Direct attempts may
transfer the file again. SDK resend defaults, capability schemas, provider
selection and output-artifact routing remain unchanged. See
[ADR-0012](adr/0012-source-files-for-independent-toolboxes.md).

**Validation:** the two automatic-policy regression cases failed before the
fix; the explicit direct-file controls passed. The original focused regression run passed
36 tests; the latest complete SDK run passed 250 tests. HTTP tests intercept real SDK client
requests and check source bytes, absence of artifact uploads, normal execution
and extraction failover. Unit controls cover single-endpoint compatibility,
client lifecycle and a secondary provider on a different deployment. These
checks are functional tests, not dataset evaluation or measured quality gains.

**Conclusion:** initial extraction no longer depends on an ID stored only in
another configured deployment. No dataset benchmark or production rollout has
been performed. The remaining Core/SDK corrections are described in
[the consolidated report](extraction-resilience-fixes.md).

The original full-suite run exposed a preexisting golden-manifest mismatch.
Its import-time localization cause and subsequent correction are documented in
[manifest localization](manifest-localization.md). Current validation is recorded
in the [consolidated report](extraction-resilience-fixes.md).
