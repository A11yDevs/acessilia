# 0007. Canonical manifest model and LaTeX-to-MathML conversion

- **Status:** Accepted
- **Date:** 2026-10-19
- **Components:** core, SDK, docstruct, Toolbox
- **Issues:** [#152](https://github.com/A11yDevs/acessilia/issues/152); findings A1 and A3 of the [October 2026 audit](../architecture/audit-2026-10.md)
- **Related:** [ADR-0002](0002-component-responsibilities.md), [ADR-0003](0003-remote-only-operational-capabilities.md), [ADR-0004](0004-single-source-of-truth-for-contracts.md)

## Context

Acessilia has four components with distinct responsibilities
([ADR-0002](0002-component-responsibilities.md)): the **core** decides and
orchestrates the processing; the **SDK** gives typed access to the Toolbox
capabilities; **docstruct** holds pure structural models and algorithms; the
**Toolbox** executes and exposes operational capabilities.

The audit found two questions that needed a decision:

1. **Which component holds the single definition of the processing manifest's
   semantic model.** Today the model exists twice, in
   `backend/core/manifest/models.py` and in the Toolbox's
   `core/normalization/models.py`, under the same schema id; the Toolbox
   publishes it as `artifact/structured-document@1` (finding A1).
2. **Where LaTeX → MathML conversion happens.** Today the core converts with
   `latex2mathml` in `backend/tools/formula_tools.py`, and the Toolbox has its
   own implementation behind `math.convert` (finding A3).

## Decision

### 1. docstruct is the single source of the manifest's semantic model

**docstruct is the single source of the semantic models and schemas of
document structure, including the structure of the processing manifest.** The
Toolbox remains responsible for publishing and validating the operational
contract `artifact/structured-document@1` in its APIs. That contract must be
**derived from the shared definition**, never from a competing model kept by
hand.

Two concepts must be kept apart:

- **Semantic (document) model:** elements, structure, hierarchy, location,
  provenance and document invariants. These belong to docstruct.
- **Operational envelope and contract:** capability ids, requests and
  responses, artifact references, execution, errors and API-specific
  metadata. These belong to the Toolbox.

docstruct's internal types need not be identical to the external payload.
Where they differ, an explicit adapter converts between the representations,
preserving semantics and compatibility. The public name
`artifact/structured-document@1` **does not decide where the model's source
code lives**.

Rationale:

1. **Single source of truth:** no divergence between models defined in
   different repositories, and no duplicated maintenance and tests.
2. **Cohesion:** fusion, comparison, reading order, structural validation and
   their data types stay in one domain.
3. **Dependency direction:** the core and the Toolbox may depend on docstruct,
   with no reverse dependency and no coupling of docstruct to REST, MCP or the
   SDK.
4. **External stability:** the contract the Toolbox publishes can keep its own
   versioning, independent of the internal structures, with explicit
   conversions where needed.

Constraints:

- docstruct **must stay pure, deterministic and free of mandatory external
  dependencies**, as it is today.
- The Toolbox's operational Pydantic models **must not** be moved wholesale
  into docstruct: only document concepts and invariants belong there.
  Execution metadata and planning policy stay with their own components.

### 2. The core obtains MathML through `math.convert`, via the SDK

**The core requests the conversion through the SDK, using the Toolbox
capability `math.convert`.** The `latex2mathml` implementation stays in the
Toolbox's specialized provider. **docstruct gets no `latex2mathml` extra.**

```text
core (decides when to convert)
  → SDK (contract, transport, errors)
    → Toolbox / math.convert (execution)
      → pure-math provider / latex2mathml
```

docstruct remains responsible for pure structural operations on LaTeX, such as
normalization, delimiter removal and comparison. Being a pure-Python library
does not make a converter a structural algorithm that belongs in docstruct.

Rationale:

1. **No competing implementations:** the same conversion service must not
   exist in the core, docstruct and the Toolbox at once.
2. **Separation of responsibilities:** the core decides *when* and *why* to
   convert; the Toolbox decides *how* to run the conversion under the
   contracted capability.
3. **Dependency isolation:** docstruct stays free of `latex2mathml`, and the
   core image carries no operational converters.
4. **Governance and observability:** provider versions, availability, errors,
   metrics and converter evolution are managed in the capability layer.
5. **Evolution:** new converters can implement `math.convert` without changing
   planning or the structural algorithms.

Failure handling: an unavailable or failing `math.convert` must be reported
explicitly to the core, which decides between failing, replanning or a
documented degradation. There must be **no silent local fallback** to
`latex2mathml` ([ADR-0003](0003-remote-only-operational-capabilities.md)).

### Resulting responsibilities

| Component | Responsibility |
|---|---|
| docstruct | Structural models and invariants; normalization and pure algorithms over documents and formulas |
| Toolbox | Publishing `artifact/structured-document@1`; adapting between representations; running `math.convert` and managing its provider |
| SDK | Typed client for the published contracts; transport, references, error handling and retries |
| core | PDDL planning, enrichment and accessibility decisions, calling `math.convert` and handling its results |

## Consequences

Implementation and acceptance criteria:

1. **Inventory and separate the models:** identify the document concepts
   duplicated in the core and the Toolbox, and tell semantic, operational and
   planning fields apart.
2. **Consolidate the shared definition:** place the document models and
   invariants in docstruct, with no dependency on the Toolbox, the SDK or the
   core; use schema generation or explicit adapters for the API.
3. **Preserve compatibility:** keep `artifact/structured-document@1` and its
   versioning rules; run contract tests with real fixtures before replacing
   existing models. Incompatible changes require a new versioned contract.
4. **Migrate the conversion:** replace the core's direct `latex2mathml` calls
   with calls through the SDK to `math.convert`, and remove the core's direct
   dependency **after** confirming there is no other legitimate use.
5. **Avoid duplication:** add no conversion extra to docstruct; keep only the
   pure LaTeX normalization functions there.
6. **Verify in CI:** purity and dependency direction; conformance of the
   manifest to the published contract; semantic equivalence in the adapters;
   and the handling of errors, unavailability and results of `math.convert`.

**Done when** there is a single semantic definition of the shared models, the
Toolbox payload remains compatible, the core obtains MathML only through
`math.convert` via the SDK, and tests prevent new dependencies or duplicated
implementations.

Benefits: less coupling between layers, less duplicated code, more predictable
contracts, and providers that can evolve independently.

Risks to control:

- a premature migration that breaks manifest consumers;
- confusion between the operational manifest and the canonical document;
- divergent docstruct versions in the core and the Toolbox (audit finding
  A4);
- more remote calls for simple operations.

Mitigate them with versioned adapters, contract tests, pinned versions and,
where appropriate, batch processing on the Toolbox, never with an implicit
local fallback.

In short: **docstruct defines the structure; the Toolbox publishes and runs
capabilities; the SDK connects; the core decides and orchestrates.**
