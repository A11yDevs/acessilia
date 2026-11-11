# 0016. Dataset reference contract ownership and migration

You can also read this documentation in **Brazilian Portuguese**: [português brasileiro](0016-dataset-reference-contract.pt-br.md)

- **Status:** Accepted
- **Date:** 2026-11-11
- **Components:** Dataset, Core, Toolbox
- **Issues:** [Dataset #9](https://github.com/A11yDevs/acessilia-dataset/issues/9), [Core #388](https://github.com/A11yDevs/acessilia/issues/388), [Toolbox #141](https://github.com/A11yDevs/acessilia-toolbox/issues/141)

## Context

The Core's math and presentation benchmarks and the Toolbox Dataset provider
used paths in the legacy Dataset layout. Some consumers followed a moving
revision. Moving the references or removing the legacy splits in place could
break them. The reference manifest also needs to distinguish the availability
of a file from the annotations that apply to an input and task.

## Decision

- The Dataset owns the input and reference manifest schemas and the schemas of
  the referenced files. It publishes them alongside the data at the same
  revision and validates them in CI. Contract changes declare a version and
  the supported migration.
- The Core owns benchmark criteria, scorecard protocols and historical
  comparison fixtures. Its CI pins a Dataset commit and checks the references
  without a Toolbox service. The public benchmark readers also support local
  trees and record the Git revision when available and the reference digest.
  For exports verified against the lock, the pinned commit is recorded as
  `expected_revision`. Comparisons require
  matching reference identity, criteria and protocol.
- The Toolbox owns its published API schemas and resolves Dataset inputs and
  references at the same immutable commit. The effective commit enters cache
  keys and provenance. Coverage and selectors live in versioned item metadata.
  Changes to a published response schema require compatibility review and
  follow the Toolbox's contract versioning policy. The review for this
  transition retains the Dataset response schemas at `@1`: `sha256` and
  `artifact_id` were already nullable in `DatasetArtifactRef` and could be
  serialized as null, so their schema change corrects the published
  declaration. The public item, artifact reference, and split schemas continue
  to allow additional properties. Producer models retain their existing
  validation. The optional `deprecated` split field is additive. Required fields are
  unchanged, and every response shape emitted by the existing provider remains
  valid; the optional flag adds deprecation information. No capability version
  bump is required for this transition. Removing a field,
  making an optional field required, narrowing a value type, or changing the
  meaning of an existing field requires a new major schema/capability version
  and a consumer migration.
- The new manifest takes precedence when the revision declares the new layout.
  Consumers report a missing, malformed or unsupported required manifest or
  reference as an error. A valid empty collection, a task without annotation
  and an annotated negative have distinct meanings.

### Migration order

1. Prepare and verify both consumers against the published legacy commit.
   Preserve the fixtures they need with source revisions and hashes.
2. Publish and tag a compatible Dataset revision with `references/` and the
   legacy paths side by side. With one pull request per repository, the
   compatibility revision can be published before the consumer pull requests
   merge because it keeps the legacy layout intact.
3. Update both consumers to the same exact Dataset commit and run their CI.
   Verify that the pinned commit is fetchable from the upstream repository.
   If the merge strategy changes its SHA, retain the exact pinned commit under
   the transition tag or update both pins to the published commit.
4. Retire the legacy paths in a separately tagged revision after both
   consumers migrate and their regression checks pass. Ship the Toolbox
   deprecation flag for at least one release before dropping the public
   splits from the default layout. Keep explicit historical revisions
   accessible under the documented provider policy.

## Consequences

The consumers can migrate independently while the layouts coexist. The
Dataset validator checks the schema and migrated file hashes. The Core's
offline smoke test and the Toolbox's pinned-fixture contract tests verify
consumer compatibility. Publication still depends on the Dataset's
permissions review, and the contract tests do not establish redistribution
rights.
