# 0032. Toolbox operations use local libraries within deployment families

Brazilian Portuguese: [português brasileiro](0032-toolbox-runtime-library-placement.pt-br.md).

- **Status:** Accepted
- **Date:** 2026-11-27
- **Components:** core, SDK, docstruct, Toolbox
- **Issues:** [#913](https://github.com/A11yDevs/acessilia/issues/913), [#804](https://github.com/A11yDevs/acessilia/issues/804), [#639](https://github.com/A11yDevs/acessilia/issues/639), [#735](https://github.com/A11yDevs/acessilia/issues/735)
- **Builds on:** [ADR-0002](0002-component-responsibilities.md), [ADR-0003](0003-remote-only-operational-capabilities.md); refines the runtime placement proposed in [ADR-0028](0028-operational-execution-in-the-toolbox.md).

## Context

Moving an operation out of the Core does not determine whether each function
needs a service. The Toolbox already installs a hash-pinned Docstruct wheel,
runs lightweight adapters locally and delegates heavy providers to sidecars.
Its capability/provider registries already dispatch both kinds of execution.
The [source inventory and migration map](../architecture/toolbox-runtime-placement.md)
records the inspected revisions, existing mechanisms and remaining gaps.

Options considered:

| Placement | Trade-off |
|---|---|
| A central Docstruct service | Adds transport and serialization to every algorithm call and couples its consumers' scaling. |
| One container per capability | Offers isolation but multiplies deployment and communication for small functions. |
| One image with every provider | Simplifies dispatch but couples incompatible dependencies, models and resources. |
| Local libraries within appropriate deployment families | Reuses the existing lightweight process and sidecars; separates services when their resource or isolation needs justify it. Chosen. |

## Decision

1. **Separate algorithm, capability and deployment boundaries.** Docstruct
   remains an independent pure library. Toolbox-owned operational functions
   call it locally; a versioned capability exposes a bounded semantic
   operation; deployment groups compatible operations by resource needs.
   These are not one-to-one mappings.
   An operation is a candidate PDDL action when it has independently relevant
   preconditions/effects, contributes to an obligation, or requires a Core
   strategy/acceptance/replanning decision. Technical substeps of one bounded
   action stay internal; a function need not become a capability or an action.
2. **Use the existing Toolbox process first.** Put migrated compositions in
   the internal `acessilia_toolbox.operations` package as the first slice
   needs it, with thin registered adapters. Do not copy Docstruct algorithms
   or move the operation-id/cancellation registry in `core/operations.py`:
   it has a different responsibility. A separately published runtime package
   requires a concrete external importer and a subsequent decision.
3. **Keep heavy or incompatible execution isolated.** Reuse current sidecars.
   A new worker/image/service needs evidence of GPU/runtime requirements,
   dependency incompatibility, failure isolation or independent scaling.
   A family is a placement category, not a requirement to add a container.
4. **Reuse the public registry and execution boundary.** Resolve capability
   identity/version and the selected provider through existing registries,
   executor and adapter factories. A function calls another local function
   directly, without loopback REST/MCP or a second capability catalogue.
   Reusing a public capability internally must preserve its required validation,
   authorization, errors, cancellation, provenance and cache semantics where
   applicable. This does not require recursive executor calls; admission must
   avoid holding a slot while waiting on the same saturated pool.
   Cross-process work uses the published provider contract.
5. **Keep workflow authority in the Core.** Goals, targets, semantic provider
   choices, alternatives, acceptance and replanning stay there. Operational
   compositions execute a bounded, explicit contract and return observations,
   results, typed failures and provenance. They do not create obligations or
   choose a workflow. Decompose legacy agents by responsibility; agents and
   their decisions remain in the Core.
   Resolving a compatible implementation/instance or failing over infrastructure
   under an authorized policy must preserve the requested semantics and
   provider/version constraints. Replacing Docling with MinerU or OCR with VLM
   is a semantic alternative, not an availability decision hidden in dispatch.
   Use bounded operational DTOs, never the Core's complete `ProcessingManifest`
   or its goals, obligations and attempts as a new capability's contract (#908).
6. **Keep dependencies and releases explicit.** Toolbox runtime → Docstruct;
   Core → public SDK → capability contract. The runtime imports neither Core
   nor Core SDK. Release it with the Toolbox; pin Docstruct's wheel/hash and
   record runtime/provider/algorithm versions in provenance and cache identity.
   Install only the extras each image needs, from its lockfile.
   In 0.3.0, Core may still use the contract/data representations permitted by
   the [Docstruct import inventory](../architecture/docstruct-import-inventory.md).
   Existing computational imports remain pinned migration debt; remove them
   with each slice. This permits no new local algorithms or wider allowances
   and does not anticipate the reference-only proposal in #914.
7. **Migrate one semantic slice at a time.** Publish a compatible contract
   and implementation first, then switch its Core consumer with differential
   evidence, and shrink the transitional/import allowlists. Preserve required
   ids, metadata, target scope, failure semantics and checkpoint behavior.
   Batch small transformations where the contract permits; measure requests,
   bytes and latency before claiming a performance improvement.
   Each slice declares repeat/recovery, effects, timeout and publication rules;
   job, operation, input, cache and idempotency identities are not interchangeable.
   Correlate observations with the processed input/context and contract versions;
   Core must reject stale results before applying them, even when target ids match.
   The [migration gates](../architecture/toolbox-runtime-placement.md#first-slice-and-acceptance-gates)
   detail these requirements without introducing distributed idempotency here.

## Consequences and scope

This decides placement and invocation for migrated operations. The SDK's
current local operations stay transitional until their consumers migrate;
it does not remove them by repackaging. Existing contracts remain the source
of truth until the shared-contract decision is made. ADRs 0027–0030 retain
their own `Proposed` status and unresolved scope.

The first planned slice is `norm-fix`; existing `text.postprocess@1` has
different output and behavior. The migration map separates reuse from new
contracts and identifies execution families, contract status and the responsible
side. No Docker topology, runtime behavior,
MCP transport or queue implementation changes in this decision PR.

Current semaphore/threadpool admission and process-local operation joining
are not a durable distributed queue. Async execution belongs to #639.
Cancellation acknowledgment is not proof that synchronous computation was
preempted. Artifact references remain preferred; this decision does not make
the Core reference-only or plan the bootstrap (#914/#816).

Compliance uses existing purity, dependency, isolated-install and differential
checks plus each migration's contract tests. The inventory records the
Toolbox's missing `acessilia_core` guard and its follow-up; it is not claimed
to be enforced already. Cross-component owners review this decision through
the ADR process before merge; `Accepted` describes its state after merge.
