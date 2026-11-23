# 0028. All document computation runs in the Toolbox

You can also read this documentation in **Brazilian Portuguese**: [português brasileiro](0028-operational-execution-in-the-toolbox.pt-br.md)

- **Status:** Proposed
- **Date:** 2026-11-22
- **Components:** core, SDK, docstruct, Toolbox
- **Issues:** [#735](https://github.com/A11yDevs/acessilia/issues/735), [#632](https://github.com/A11yDevs/acessilia/issues/632), [#639](https://github.com/A11yDevs/acessilia/issues/639), related: [#656](https://github.com/A11yDevs/acessilia/issues/656)
- **Amends, if accepted:** [ADR-0002](0002-component-responsibilities.md) (the SDK row, "in-process access to docstruct's pure algorithms", and the dependency chart), [ADR-0017](0017-operational-sdk-and-agentic-core.md) (operations run by the caller), [ADR-0003](0003-remote-only-operational-capabilities.md) (what "operational" covers), and principles P2, P3 and 5 of the [constitution](../constitution.md)

## Context

ADR-0003 sends to the Toolbox what needs "an external tool, a model or
specialized infrastructure", and principle 5 of the constitution lets
deterministic extraction run "as a Toolbox capability or a docstruct
algorithm". ADR-0017 adds that the SDK offers reusable operations and
deterministic workflows, run in the caller's process. So today pure
computation over documents runs inside the core. As measured on `develop`
(`46f2fe7e`):

- **46 files** in the core and `backend/` import docstruct directly. **43** of
  them import computation; the other 3 import only contracts or validation
  (`manifest/models.py`, `manifest/document_adapter.py`,
  `pipeline/validators.py`). The computation includes `fusion.xycut`,
  `fusion.tailjoin`, `fusion.verse`, `fusion.similarity`, `geometry`,
  `tables.ast`, `text.latex`, `text.norm_fix`, `text.unicode_repair`, and also
  the export renderers `docstruct.export.*` (txt, html, markdown, page text,
  formats, filters, Pandoc AST: 7 files, including the accessibility filters),
  `docstruct.sections`, `docstruct.blocks.lists` and `docstruct.data_uri`.
- Of the **25** plan methods in `METHOD_HANDLERS`, **14** compute locally,
  meaning that their handler runs no capability and no model call:
  `latex-normalizer`, `norm-fix`, `unicode-repair`, `rep-guard`,
  `line-number-extractor`, `verse-chunker`, `tailjoin`, `tailjoin-positioned`,
  `xycut-order`, `skeleton-order`, `rescue-omitted`, `table-smart-fusion`,
  `agreement-rule`, `deterministic-heading-repair`. The rest call the Toolbox
  (`dual-provider-fusion`, `single-provider`, `vision-page-inspection`,
  `pymupdf-region`, `vlm-pairwise-judge`, `mathml`, `latex-verbalizer`),
  verify work that enrichment already did remotely (`vision-description`,
  `pandoc-table`, `pandoc-code`), or are symbolic (`human-review`). Only the
  first 5 of these declare requirements to the availability gate
  (`METHOD_TOOLBOX_REQUIREMENTS`).
- **3** SDK operations run in the core's process:
  `acessilia_sdk.operations.formula`, `fusion` and `page_judge`. Their only
  consumers are the core, the benchmarks (`scripts/bench`) and tests.
- The SDK itself imports docstruct computation (`fusion.payload`,
  `geometry.boxes`, `imaging`, `policy`, `text.latex`) besides the
  `manifest` contract.
- The core's non-computational docstruct imports are contracts
  (`docstruct.canonical`, `docstruct.manifest`, `docstruct.types`),
  validation (`docstruct.validation`), shared vocabularies
  (`docstruct.placeholders`, `docstruct.profiles`) and policy
  (`docstruct.policy`, for example `verbosity_for_mode` in
  `backend/service.py`).

[#735](https://github.com/A11yDevs/acessilia/issues/735) asks for a core that
only plans and coordinates (ADR-0029), with every effect on a document being a
capability invocation the planner chose and can observe, retry, cache and
attribute. Local computation is invisible to the plan: it cannot be checked for
availability, cached by the Toolbox, cancelled through ADR-0019 or recorded
with provider provenance.

Options considered:

1. **Keep pure docstruct algorithms in the core.** Cheap and deterministic;
   satisfies ADR-0003 today. But it leaves two kinds of step, planned
   capabilities and hidden local code, and keeps the core's dependency on
   computation.
2. **Move docstruct into the Toolbox repository.** Rejected by #632 (§3.4):
   docstruct is a shared, independent library.
3. **Docstruct stays an independent library; the Toolbox runs it.** The core
   keeps only docstruct's contract types. Chosen.

## Decision

Four things are decided separately: where document computation **runs**, who
**owns** the operational runtime, where the **library** lives, and where the
**contracts** live.

### Execution: the Toolbox runs all document computation

- The core must not run document computation in its own process. Structural
  algorithms (fusion, ordering, geometry, normalization, tables, text and
  Unicode repair, math normalization) and compositions of capabilities run as
  Toolbox capabilities, atomic or composite.
- The migration starts with an inventory of every `docstruct.*` import in the
  core and `backend/`, classified as contract, algorithm, validation, policy
  or operation. Policy (decision rules such as `verbosity_for_mode`) belongs to
  the core (ADR-0029): it moves into the core or is allowlisted explicitly.
  Export rendering (`docstruct.export.*`) is computation: accessible export is
  a planned action (ADR-0029) backed by Toolbox capabilities. Each algorithm or operation gets an equivalent capability; the
  call site switches to the generic client (ADR-0027); the import is removed.
- Migration is per plan method (P8), with a differential test that compares
  the manifest produced before and after.

### Ownership: the operational runtime belongs to the Toolbox

- The SDK is split physically (#639):
  - **`acessilia-core-sdk`**: the generic capability client, contracts as
    consumed, transport, authentication, typed errors, artifact references.
    It must not run document operations, depend on docstruct algorithms,
    import Toolbox internals, carry provider dependencies (OCR, VLM,
    renderers) or plan.
  - **Toolbox operational runtime**: reusable operations, compositions of
    capabilities, input and output adaptation, the integration with docstruct
    algorithms, and functions used by the workers. It must not plan, depend on
    the core or the core SDK, or coordinate workflows.
- The runtime is owned by the Toolbox. By default it is a package inside the
  Toolbox (`acessilia_toolbox.operations`), released with it, because no
  consumer needs to **import** it: the core, the benchmarks and the tests reach
  it through capability invocation. A benchmark or script in this repository
  must not import a package shipped inside the Toolbox (P3, P4). The runtime
  becomes a separately distributed `acessilia-toolbox-sdk` only when a concrete
  consumer needs to import it.
- `acessilia-sdk` keeps a temporary compatibility layer over the core SDK, with
  a published deprecation policy.

### Library: docstruct stays independent

- Docstruct stays a pure, deterministic, independent library with no heavy
  operational dependency and no dependency on the core or the Toolbox. The
  Toolbox installs it at a pinned version (P3). It is not moved into the
  Toolbox's source. A repository of its own may be considered later; it is not
  required for 0.3.0.

### Contracts: the core should not need docstruct for them

- Until a contracts decision is taken, the core may import only docstruct's
  contract modules, kept as an allowlist in `tests/test_architecture_layers.py`.
  The allowlist of computational modules still imported during the migration
  can only shrink.
- Target: the core does not install a library of document algorithms only to
  read interoperability contracts. Extracting the shared interoperability
  models and schemas (canonical document, manifest, envelopes) into a
  contracts package, for example `acessilia-contracts`, is to be evaluated in a
  follow-up ADR. That ADR amends ADR-0004 and P7 (docstruct currently owns the
  canonical models), keeps one source of truth, and leaves the internal
  structures of algorithms in docstruct.

### Constitution

- If accepted, the constitution is amended in a follow-up pull request:
  - P2: the SDK no longer provides "access to reusable libraries" for
    computation, and the Toolbox owns the operational runtime;
  - P3: core → docstruct becomes "core → docstruct contract modules", and SDK
    → docstruct becomes "Toolbox runtime → docstruct" (both point at the
    contracts package instead, if it is extracted);
  - principle 5: deterministic extraction runs as a Toolbox capability.

## Open decisions

This ADR stays `Proposed` until these are closed in review:

- **Contracts package.** Whether the shared interoperability contracts are
  extracted (and from which modules) is decided by the follow-up ADR. Until
  then the contract allowlist applies.
- **Classification.** The inventory pull request classifies every import
  listed above, including the policy and vocabulary modules. Its review closes
  which modules stay allowlisted.
- **Cross-component review.** The Toolbox's and docstruct's owners review the
  runtime ownership and the dependency changes (ADR process, step 5). After
  that, a follow-up pull request sets `Accepted`.

## Consequences

- Every effect on a document is a capability call: available to the planner,
  cached and attributed by the Toolbox, and cancellable.
- More remote calls and larger payloads. Mitigations: artifact references
  (ADR-0015), composite capabilities sized to avoid chatty sequences, and the
  Toolbox result cache.
- Benchmarks, the CLI and local development need a running Toolbox for every
  step, not only for heavy ones. The Toolbox's local Compose setup becomes a
  prerequisite of the core's end-to-end tests.
- The Toolbox runs pure algorithms too. Its stateless model is unchanged
  (durable queues are a separate decision, #639).
- Progress indicators, with the baseline above, are tracked in #735: core files
  importing computational docstruct modules (43), plan methods that compute
  locally (14 of 25), SDK operations run in the core (3). Each must reach zero.
- When this ADR is accepted, ADR-0002's back-reference is updated to "Amended
  by ADR-0017 and ADR-0028".
- Compliance: `tests/test_architecture_layers.py` (docstruct contract
  allowlist, shrinking computational allowlist, no core → Toolbox runtime
  dependency), the isolated install jobs of the core SDK and of the Toolbox
  runtime, and the differential tests of each migrated method.
