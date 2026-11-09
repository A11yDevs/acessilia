# 0015. The artifact reference contract, `artifact/reference@1`, phased

You can also read this documentation in **Brazilian Portuguese**: [português brasileiro](0015-artifact-reference-v1.pt-br.md)

- **Status:** Accepted
- **Date:** 2026-11-09
- **Components:** core, SDK, Toolbox
- **Issues:** [#185](https://github.com/A11yDevs/acessilia/issues/185) (P5), [#152](https://github.com/A11yDevs/acessilia/issues/152)
- **Supersedes:** [ADR-0005](0005-artifact-references.md)

## Context

[ADR-0005](0005-artifact-references.md) decided reference-oriented processing
and asked the Toolbox to publish the reference model as `artifact-ref@1`, with
`id`, `digest`, `media_type`, `size`, `store`, `scope` and provenance. The
review of [#185](https://github.com/A11yDevs/acessilia/issues/185) found that
this cannot be published as written:

- **The name clashes.** The Toolbox manifests of `artifact.store` and
  `artifact.retrieve` already cite `artifact/reference@1`, following the
  Toolbox convention (`artifact/<name>@<major>`, file
  `schemas/<name>@<major>.json`, `$id` `urn:a11y-devs:schema:<name>:<semver>`).
  No file exists for it, and ADR-0005 uses another name.
- **The Toolbox cannot state scope or provenance today.** Its `ArtifactRef`
  (`core/artifact.py`) has `artifact_id`, `media_type`, `size`, `uri`,
  `storage_backend` and `filename`. It has no explicit `digest`; the digest is
  in the content-addressed id.
- **Access is per deployment, not per reference.** Every artifact route
  requires the deployment's API key (`require_api_key`). The id alone grants
  nothing, but a key that reads one artifact reads all of them. A per-reference
  scope check is new behaviour, and the refactoring cycle keeps behaviour
  changes apart from standardization (P8).
- **Provenance has no home yet.** Whether it lives in the reference or in the
  artifact's metadata is still open.

## Decision

The principles of ADR-0005 stay; the contract is published in two versions.

- **Process where stored.** Persisted artifacts are processed where they are
  stored. Services pass typed, opaque references instead of documents or
  canonical trees.
- **The Toolbox owns the reference contract,** per
  [ADR-0004](0004-single-source-of-truth-for-contracts.md). Its name is
  `artifact/reference@1`, in `schemas/reference@1.json`, with `$id`
  `urn:a11y-devs:schema:reference:1.0.0`. The SDK consumes it; there is no
  second name for the same reference.
- **`artifact/reference@1` holds what the Toolbox can state today:**
  - `artifact_id`: the content-addressed id, opaque to clients, stable and
    immutable;
  - `digest`: written `sha256:<64 hex>`, and equal to the digest in
    `artifact_id`;
  - `media_type` and `size`;
  - `store`: the logical store that holds the artifact. The Toolbox's current
    `storage_backend` maps to it through an adapter, not as a second field.
- **`@2` only adds fields.** It adds `scope`, which says who may read the
  artifact, and provenance: the capability, provider and versions that
  produced it, and the input references. No `@1` field is renamed or removed.
- **Scope is checked before use, from `@2`.** Until then, access is granted by
  the deployment's API key, and the id is never treated as a credential.
- **Documents with their own schemas stay separate.** `pdf-export@1` and
  `image@2` keep their fields; turning them into full references is a
  separate contract change.
- **Clients that only hold an id keep working.** The SDK keeps a helper that
  parses an id (with or without the `sha256:` prefix) next to the model
  generated from the schema. Missing fields are never invented.
- **Artifacts are immutable.** A changed artifact is a new artifact with a new
  reference.
- **Materialization is explicit.** A client downloads the bytes only when it
  needs them and verifies them against the digest. A digest mismatch is a
  contract violation, never a "not found", so it does not trigger the resend
  of [ADR-0014](0014-artifact-download-not-found-failover.md).
- **References stay valid across replicas.** Replicas of one Toolbox
  deployment share the store, so a reference is valid on all of them (see
  [ADR-0006](0006-availability-and-failover.md)). Across independent
  deployments, a reference is valid only where its store is reachable.
- **Small objects do not need references.** Inputs and outputs that fit
  comfortably in a request or response, such as a LaTeX formula, a short
  text or a page judgement, travel inline.

## Consequences

- **Toolbox:** publishes `schemas/reference@1.json` and the
  `storage_backend` → `store` adapter
  ([acessilia-toolbox#145](https://github.com/A11yDevs/acessilia-toolbox/issues/145)), together with the
  other schemas its manifests cite without a file
  ([acessilia-toolbox#142](https://github.com/A11yDevs/acessilia-toolbox/issues/142)).
  The per-reference scope check is
  [acessilia-toolbox#146](https://github.com/A11yDevs/acessilia-toolbox/issues/146).
- **SDK:** `ArtifactRef` in `acessilia_sdk.toolbox.artifacts` stays
  provisional until a model is generated from `artifact/reference@1`
  ([#213](https://github.com/A11yDevs/acessilia/issues/213)), with standard
  library code only and regeneration checked in CI. The id-parsing helper
  stays. [#185](https://github.com/A11yDevs/acessilia/issues/185) states the
  compatibility between SDK and Toolbox versions and for stored references.
- **Deviation that remains:** no per-reference scope until `@2`; a deployment
  key reads every artifact of that deployment.
- **Verified today:** `libs/sdk/tests/test_failover.py` checks digest
  verification, atomic writes and downloading from the endpoint that served
  the call.
- **Planned verification:** contract tests against `artifact/reference@1`,
  including the rule that `digest` equals the id's digest.
