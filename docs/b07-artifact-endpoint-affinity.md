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
fix; the explicit direct-file controls passed. The focused core suite now has
36 passing tests; all 246 SDK tests passed. HTTP tests intercept real SDK client
requests and check source bytes, absence of artifact uploads, normal execution
and extraction failover. Unit controls cover single-endpoint compatibility,
client lifecycle and a secondary provider on a different deployment. These
checks are functional tests, not dataset evaluation or measured quality gains.

**Conclusion:** initial extraction no longer depends on an ID stored only in
another configured deployment. No dataset benchmark or production rollout has
been performed. Output downloads (B05) and other Trilha B findings remain
separate pending work in the consolidated PRs.

Full core validation: 1,754 passed, 51 E2E tests deselected, and one existing
golden-manifest mismatch in
`test_manifest_wire_payload_matches_the_golden_file[toolbox-v2-contract]`.
The same test fails on an unmodified archive of the base commit; it was not
introduced by B07. The PR remains a draft and does not claim a green full suite.
