# 0028. All document computation runs in the Toolbox

You can also read this documentation in **Brazilian Portuguese**: [português brasileiro](0028-operational-execution-in-the-toolbox.pt-br.md)

- **Status:** Proposed
- **Date:** 2026-11-22
- **Components:** core, SDK, docstruct, Toolbox
- **Issues:** [#735](https://github.com/A11yDevs/acessilia/issues/735), [#639](https://github.com/A11yDevs/acessilia/issues/639), [#656](https://github.com/A11yDevs/acessilia/issues/656)
- **Amends, if accepted:** [ADR-0017](0017-operational-sdk-and-agentic-core.md) (operations run by the caller), [ADR-0003](0003-remote-only-operational-capabilities.md) (what "operational" covers), and principles P2, P3 and 5 of the [constitution](../constitution.md)

## Context

ADR-0003 sends to the Toolbox what needs "an external tool, a model or
specialized infrastructure", and principle 5 of the constitution lets
deterministic extraction run "as a Toolbox capability or a docstruct
algorithm". ADR-0017 adds that the SDK offers reusable operations and
deterministic workflows, run in the caller's process. So today pure
computation over documents runs inside the core. As measured on `develop`
(`46f2fe7e`):

- **46 files** in the core and `backend/` import docstruct directly, mostly
  computation: `fusion.xycut`, `fusion.tailjoin`, `fusion.verse`,
  `fusion.similarity`, `geometry`, `tables.ast`, `text.latex`,
  `text.norm_fix`, `text.unicode_repair`.
- Of the **25** plan methods in `METHOD_HANDLERS`, **5** declare Toolbox
  requirements; about **20** compute locally over docstruct (`xycut-order`,
  `tailjoin`, `norm-fix`, `unicode-repair`, `verse-chunker`,
  `latex-normalizer`, `agreement-rule`, `table-smart-fusion`, ...).
- **3** SDK operations run in the core's process:
  `acessilia_sdk.operations.formula`, `fusion` and `page_judge`.

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

- The core must not run document computation in its own process. Structural
  algorithms (fusion, ordering, geometry, normalization, tables, text and
  Unicode repair, math normalization) and compositions of capabilities run as
  Toolbox capabilities, atomic or composite.
- The core may import from docstruct only its contract modules: the canonical
  document models and schemas it reads and writes (for example
  `docstruct.manifest`). The list is kept in `tests/test_architecture_layers.py`.
  The allowlist of computational modules still imported during the migration
  can only shrink.
- The operations in `acessilia_sdk.operations` become composite Toolbox
  capabilities. The SDK keeps contracts, clients, artifact references and
  helpers that do not compute over documents (for example localization of
  structured findings).
- Docstruct stays an independent package, with no move of repository. The
  Toolbox depends on it at a pinned version (P3, unchanged).
- Migration is per plan method (P8). Each step publishes the capability,
  switches the handler to invoke it and passes a differential test that
  compares the manifest produced before and after.
- If accepted, the constitution is amended in a follow-up pull request:
  - P2: the SDK no longer provides "access to reusable libraries" for
    computation;
  - P3: core → docstruct becomes "core → docstruct contract modules";
  - principle 5: deterministic extraction runs as a Toolbox capability.

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
  importing computational docstruct modules (46), local plan methods (about 20
  of 25), SDK operations run in the core (3). Each must reach zero.
- Compliance: `tests/test_architecture_layers.py` (docstruct contract
  allowlist, shrinking computational allowlist) and the differential tests of
  each migrated method.
