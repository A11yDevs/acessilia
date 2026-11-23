# 0029. The core plans and coordinates: every semantic workflow step is planned

You can also read this documentation in **Brazilian Portuguese**: [português brasileiro](0029-symbolic-core-every-step-planned.pt-br.md)

- **Status:** Proposed
- **Date:** 2026-11-22
- **Components:** core, Toolbox
- **Issues:** [#735](https://github.com/A11yDevs/acessilia/issues/735), [#640](https://github.com/A11yDevs/acessilia/issues/640), [#632](https://github.com/A11yDevs/acessilia/issues/632), [#619](https://github.com/A11yDevs/acessilia/issues/619)
- **Builds on:** [ADR-0020](0020-job-resumption-and-operation-journal.md), [ADR-0027](0027-mcp-core-toolbox-contract.md), [ADR-0028](0028-operational-execution-in-the-toolbox.md)

## Context

The core already plans with PDDL in a closed loop: `PddlProblemCompiler`,
`PlannerAgent`, `NominalPlan`, `ExecutorAgent` and replanning bounded by
`max_replans` (#640). But the plan covers only part of a job. As measured on
`develop` (`46f2fe7e`):

- `domain_v2.3.pddl` has **3 generic actions**: `start-job`,
  `execute-obligation` and `complete-job`. The planner orders obligations; it
  does not model capabilities, their preconditions or their effects.
- `PddlAccessibilityOrchestrator.execute` runs **four stages in a fixed
  sequence, before planning**: media inspection, the page limit, structural
  extraction and the enrichment stages.
- Which method satisfies an obligation is decided by the method registry
  (`METHOD_HANDLERS`), not by the domain.
- Capability availability is applied by `toolbox_gate` outside the planner. Its
  default is `observe`. In `enforce` it removes methods, and the planner "falls
  back to local methods", which ADR-0028 removes.
- Agents in `acessilia_core.agents` (fusion, adjudication, vision, table
  specialist, page level) take decisions and call models from the core.

The Toolbox already publishes the semantic side of its capabilities:
predicates, per-capability actions and domain fragments
(`/planning/domain-fragments`, MCP resources `acessilia://...`; see the
Toolbox's `docs/pddl.md`). It does not own planning. #632 (PR 2) forbids a
generic MCP → PDDL compiler, and #640 treats fragment composition as
experimental.

## Decision

### What the core is

- The core is responsible for planning, reasoning, coordination and the
  logical state of workflows. It does not run operational capabilities or
  document-processing algorithms (ADR-0028).
- It still computes what planning and coordination need: compiling problems,
  composing and validating domains, keeping the logical state and the
  journal, checking observed effects, applying policies, correlating results
  and replanning. That is not document computation.

### Every semantic step is an action

- Every **semantically relevant** step of a job must be an action of the
  planning domain: steps that change the document or decide the workflow, such
  as inspection, the page limit, extraction, OCR, block fusion, reading order,
  image description, adjudication, math normalization and accessible export.
  The orchestrator must not run a fixed sequence of such steps.
- Infrastructure stays out of the domain and belongs to the runtime: HTTP
  retries, credential renewal, serialization, operational persistence, queue
  acknowledgements, health checks, artifact transport and retrieval.
- A composite capability may run several internal operations as one action.
  Its internal steps are not PDDL actions.
- An operational action must be bound to one Toolbox capability, by id and
  exact version, invoked through the generic client (ADR-0027). Other actions
  are symbolic only: recording state, `human-review`, completing the job.

### The domain is composed from versioned fragments

- The effective domain is the core's workflow actions plus the PDDL fragments
  the Toolbox publishes for the capabilities in the catalogue snapshot.
- Fragments are curated and versioned with their capability. Composition
  checks names and types; it does not translate tool schemas into PDDL (no
  generic compiler, #632).
- CI must parse the composed domain and solve a set of fixture problems with
  the internal planner and Fast Downward.

### State, availability and failure

- The problem is compiled from observed state: the manifest's facts, the
  obligations, the results already recorded and one catalogue snapshot.
- Capability and provider availability are predicates of the problem.
  `toolbox_gate` is reduced to reporting.
- An unsolvable problem is an explicit outcome: the job fails with the cause,
  or a `human-review` action is planned. It is never a silent degradation.
- A capability result updates the symbolic state once per `operation_id`,
  through the journal of ADR-0020. A duplicate or late result is ignored.
- Replanning stays in the core and stays bounded.

### Strategic agents stay in the core; operational agents are capabilities

- The agents in `acessilia_core.agents` are classified as strategic or
  operational.
- **Strategic agents stay in the core**: interpreting goals, decomposing
  tasks, choosing strategies, coordinating subplans, evaluating state and
  goals, deciding to replan, and the future LLM + planning integration of
  #619.
- **Operational agents become Toolbox capabilities**: OCR and semantic
  extraction, document classification, image description, visual
  adjudication, table and formula extraction, multimodal processing.
- Model calls go through the Toolbox (ADR-0012), including those a strategic
  agent makes. The core interprets their results in the context of the plan.
  The Toolbox never decides global goals or replanning.
- Contracts distinguish an operational result from a strategic decision.

### Planner and coordination are separate

- A `PlanningEngine` interface (#632, PR 3) separates the planner from the
  coordination of the workflow. The internal planner and Fast Downward stay
  interchangeable behind it, and their comparison keeps running.

## Consequences

- The plan explains every semantic step of the job; availability,
  alternatives and dead ends come from the domain instead of code paths.
  Keeping infrastructure out of the domain keeps it small. This is the symbolic baseline
  for #619.
- The domain grows with the catalogue. Fragment curation, action costs and the
  CI planning fixtures keep it tractable.
- Migration is incremental and follows ADR-0028, method by method. Then the
  four fixed stages become actions, and then the operational agents become
  capabilities. The closed loop does not wait for durable queues
  (#639): synchronous MCP calls are enough.
- Progress indicators are tracked in #735: stages outside the plan (4), methods
  without a capability binding (about 20 of 25), operational agents still in
  the core.
- Compliance: the CI planning fixtures; an orchestrator test that every step of
  a job comes from the plan; `tests/test_architecture_layers.py` for model
  clients in the core.
