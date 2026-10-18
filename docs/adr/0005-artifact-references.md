# 0005. Reference-oriented processing with `ArtifactRef`

You can also read this documentation in **Brazilian Portuguese**: [português brasileiro](0005-artifact-references.pt-br.md)

- **Status:** Accepted
- **Date:** 2026-10-18
- **Components:** core, SDK, Toolbox
- **Issues:** [#152](https://github.com/A11yDevs/acessilia/issues/152) (P5)

## Context

The Toolbox stores artifacts in object storage (MinIO) and identifies them by
the SHA-256 of their content. Several capabilities already return an
`artifact_id` instead of the bytes; `document.export.pdf_ua` is one. Other
flows still send whole documents or canonical trees between services, or
upload the same file again for each capability call. The SDK added
`ArtifactRef` and `download_artifact` in
[#153](https://github.com/A11yDevs/acessilia/pull/153), as a provisional model.

## Decision

- **Process where stored.** Persisted artifacts are processed where they are
  stored. Services pass typed, opaque references (`ArtifactRef`) instead of
  documents or canonical trees.
- **The Toolbox owns the reference model.** It publishes it as a versioned
  schema, `artifact-ref@1`, per
  [ADR-0004](0004-single-source-of-truth-for-contracts.md). The SDK consumes
  that schema.
- **Minimum content of a reference:**
  - `id`: opaque to clients, stable and immutable;
  - `digest`: algorithm and value, so clients can verify downloads;
  - `media_type` and `size`;
  - the logical `store` that holds it;
  - its `scope`, which says who may read it;
  - provenance: the capability, provider and versions that produced it, and
    the input references.
- **Artifacts are immutable.** A changed artifact is a new artifact with a new
  reference.
- **Materialization is explicit.** A client downloads the bytes only when it
  needs them, and verifies them against the digest. The SDK's
  `download_artifact` streams, verifies and writes atomically.
- **Scope is checked before use.** The Toolbox validates a reference's scope
  and permissions before reading or processing it. A reference is not a
  capability token by itself.
- **References stay valid across replicas.** Replicas of one Toolbox
  deployment share the store, so a reference is valid on all of them (see
  [ADR-0006](0006-availability-and-failover.md)). Across independent
  deployments, a reference is valid only where its store is reachable.
- **Small objects do not need references.** Inputs and outputs that fit
  comfortably in a request or response, such as a LaTeX formula, a short
  text or a page judgement, travel inline.

## Consequences

- **SDK:** `ArtifactRef` in `acessilia_sdk.toolbox.artifacts` is marked
  provisional. It is replaced by the model generated from `artifact-ref@1`
  once the Toolbox publishes that schema; this needs a Toolbox issue. Upload
  (`upload_artifact`, today in the core's legacy `ToolboxClient`) moves to
  the SDK next to the download, in #150 F1.
- **Verified today:** `libs/sdk/tests/test_failover.py` checks digest
  verification, atomic writes and downloading from the endpoint that served
  the call.
- **Planned verification:** contract tests against `artifact-ref@1` once it is
  published.
