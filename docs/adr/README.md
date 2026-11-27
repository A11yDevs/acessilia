# Architecture Decision Records

You can also read this documentation in **Brazilian Portuguese**: [português brasileiro](README.pt-br.md)

An Architecture Decision Record (ADR) captures one significant architectural
decision: its context, the decision itself and its consequences. This
directory is the **single source of truth for decisions that cross component
boundaries** in the Acessilia ecosystem: the core (`libs/core`, package `acessilia_core`), the SDK
(`libs/sdk`), docstruct (`libs/docstruct`) and the
[Acessilia Toolbox](https://github.com/A11yDevs/acessilia-toolbox).

Each repository may keep ADRs about its own internals. Those ADRs link to the
ones here instead of restating them.

## Index

| ADR | Title | Status |
|---|---|---|
| [0001](0001-record-architecture-decisions.md) | Record architecture decisions | Accepted |
| [0002](0002-component-responsibilities.md) | Component responsibilities and dependency direction | Accepted |
| [0003](0003-remote-only-operational-capabilities.md) | Operational capabilities run remotely, without local fallbacks | Accepted |
| [0004](0004-single-source-of-truth-for-contracts.md) | One source of truth per contract | Accepted |
| [0005](0005-artifact-references.md) | Reference-oriented processing with `ArtifactRef` | Superseded by [0015](0015-artifact-reference-v1.md) |
| [0006](0006-availability-and-failover.md) | Availability through replicas; SDK failover as a secondary mechanism | Accepted |
| [0007](0007-manifest-model-and-mathml-conversion.md) | Canonical manifest model, and MathML conversion and verbalization of formulas | Accepted |
| [0008](0008-math-capabilities-on-mathjax-and-mathcat.md) | The math capabilities run on MathJax and MathCAT | Accepted |
| [0009](0009-legacy-unicode-repair.md) | Legacy PDF Unicode repair is a pure docstruct stage orchestrated by the core | Accepted |
| [0010](0010-word-internal-spacing-diacritics.md) | Word-internal spacing diacritics are repaired; standalone ones require document evidence | Accepted |
| [0011](0011-inline-math-from-font-runs.md) | Inline math is carried as `$…$` in prose and detected from the PDF's math fonts | Accepted |
| [0012](0012-agents-reach-the-vlm-through-the-toolbox.md) | The agents can reach their vision model through the Toolbox VLM gateway | Accepted |
| [0013](0013-source-files-for-independent-toolboxes.md) | Source files for independent Toolbox deployments | Accepted |
| [0014](0014-artifact-download-not-found-failover.md) | Search endpoints for missing artifact downloads | Accepted |
| [0015](0015-artifact-reference-v1.md) | The artifact reference contract, `artifact/reference@1`, phased | Accepted |
| [0016](0016-core-package.md) | The core as a package of its own, `acessilia_core` | Accepted |
| [0017](0017-operational-sdk-and-agentic-core.md) | Operational SDK and agentic core boundaries | Accepted |
| [0018](0018-core-uses-sdk-public-api.md) | The core uses only the SDK's public API | Accepted |
| [0019](0019-operation-identifiers-and-cancellation.md) | Operation identifiers and remote cancellation | Accepted |
| [0020](0020-job-resumption-and-operation-journal.md) | Resuming a job from its durable checkpoint | Accepted |
| [0021](0021-bounded-model-call-execution.md) | Bounded model-call execution owned by the application | Accepted |
| [0022](0022-export-walker-contract.md) | A shared export walker with consumer-owned rendering policy | Accepted |
| [0023](0023-packaged-canonical-schema.md) | Package the canonical schema with an injected validation engine | Accepted |
| [0024](0024-legacy-canonical-type-deprecation.md) | Deprecate legacy canonical dataclasses while retaining compatibility | Accepted |
| [0025](0025-format-catalogue-ownership.md) | Share format identity and delivery metadata with a worker-owned plan | Accepted |
| [0026](0026-strict-canonical-export-gate.md) | Validate the canonical schema at the Core export gate | Accepted |
| [0027](0027-mcp-core-toolbox-contract.md) | Versioned capability contracts, invoked over MCP, between the core and the Toolbox | Proposed |
| [0028](0028-operational-execution-in-the-toolbox.md) | All document computation runs in the Toolbox | Proposed |
| [0029](0029-symbolic-core-every-step-planned.md) | The core plans and coordinates: every semantic workflow step is planned | Proposed |
| [0030](0030-providers-compete-per-capability.md) | Providers compete per capability; the structure suites stay structural | Proposed |
| [0031](0031-job-goals-and-plan-selection.md) | Job goals outlive the selection of a plan | Accepted |

## Process

1. **When to write one.** Write an ADR for a decision that changes
   responsibilities or dependencies between components, adds or removes an
   execution mode (for example a local executor), changes a public contract, or
   is an exception to a principle of the [constitution](../constitution.md).
2. **Format.** Copy [template.md](template.md). Use the next free number and a
   short kebab-case slug in English: `NNNN-title.md`, with its mirror at
   `NNNN-title.pt-br.md`. Keep it short; link to issues and code for detail.
3. **Language.** English is normative. A `.pt-br.md` mirror is written in the
   same pull request, following principle 8 of the constitution.
4. **Status.** The status in the file is the state the ADR has once its pull
   request is merged, because that pull request's review is the ADR's review
   (step 5). A pull request that records a decision sets it to `Accepted`. Use
   `Proposed` only to merge an ADR whose decision is still open, so it can be
   discussed in follow-up pull requests. Later statuses are
   `Superseded by NNNN` and `Deprecated`. An accepted ADR is not rewritten: a
   changed decision gets a new ADR that supersedes it. Fixing typos and links
   is fine.
5. **Review.** A cross-component ADR is reviewed by the owners of every
   component it affects. Each team keeps its technical autonomy inside its own
   component.
6. **Exceptions.** An exception to a constitution principle is recorded as an
   ADR that states the justification, the scope (which capability, which
   deployment), the owner and the exit criterion. Without such an ADR, the
   principle applies.
