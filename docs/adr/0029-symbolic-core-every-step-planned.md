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

The Toolbox already publishes part of the semantic side of its capabilities:
`GET /v1/planning/domain` (one monolithic domain, generated from the latest
version of each capability), `GET /v1/planning/capabilities/{id}` and
`GET /v1/planning/predicates`, and the MCP resources
`acessilia://planning/domain` and `acessilia://planning/capabilities/{id}`.
Per-capability fragments (`/planning/domain-fragments`) are listed in the
Toolbox's `docs/pddl.md` only as something it *may* expose. The Toolbox does
not own planning. #632 (PR 2) forbids a
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
  as inspection, extraction, OCR, block fusion, reading order, image
  description, adjudication, math normalization and accessible export. The
  orchestrator must not run a fixed sequence of such steps.
- Configuration policies stay core policies, not actions. The page limit
  (`DocumentConfig.max_pages`, checked before extraction) is one: it is an
  admission check that rejects the job with `DocumentTooLargeError`. Of the
  four stages that run before planning today, inspection, extraction and
  enrichment become actions; the page limit stays a policy.
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
  of the capabilities **and versions** in the catalogue snapshot. The Toolbox
  must serve per-capability, per-version fragments generated from a snapshot;
  the monolithic domain built from the latest versions cannot honour a plan
  that pins an older version.
- Fragments are curated and versioned with their capability. Composition
  checks names and types; it does not translate tool schemas into PDDL (no
  generic compiler, #632).
- CI must parse the composed domain and solve a set of fixture problems with
  the internal planner and with Fast Downward. Fast Downward stays optional
  at runtime, as it is in the code. Checking it in CI was left open here; that
  sub-decision is settled, while this ADR stays Proposed. Since #790, a job
  runs both backends on the current, single domain (2.4) with Fast Downward
  from a pinned image. The composed-domain part is **pending**: its fixtures
  arrive with the fragments (#640, PR 2), and the same job then covers them.

### State, availability and failure

- The problem is compiled from observed state: the manifest's facts, the
  obligations, the results already recorded and one catalogue snapshot.
- Capability and provider availability are predicates of the problem.
  `toolbox_gate` is reduced to reporting.
- An unsolvable problem is an explicit outcome, never a silent degradation:
  the job ends **escalated**, with the cause recorded. Today `human-review`
  does exactly that (its handler records the escalation and returns
  `success=False`), and it stays terminal: the job does not pause waiting for
  a person. Pausing and resuming after a human decision needs durable workflow
  state and is left to a later ADR.
- A capability result updates the symbolic state once per `operation_id`. The
  ADR-0020 journal stores identity only, "(task_id, logical slot) →
  operation_id", for the upload and extraction slots. So this ADR extends it:
  - the journal's slots cover every capability call of the plan;
  - the `execution` checkpoint keeps a **result-applied record**, the set of
    `operation_id`s whose result has been applied to the symbolic state.

  A result whose `operation_id` is already in that record, or that does not
  belong to the current plan step, is ignored.
- Replanning stays in the core and stays bounded.

### The core is agentic; the Toolbox is passive

- **The core is agentic and active**: it reasons, plans, delegates,
  coordinates, evaluates and replans. **The Toolbox is operational and
  passive**: it runs the capabilities it is asked for and returns results,
  with no agentic autonomy and no responsibility for workflow decisions.
- The Toolbox may hold atomic and composite capabilities, docstruct
  algorithms, model inference, prompts, adapters, validation and result
  processing, workers, queues, caches and operational recovery, and
  deterministic composition of operations. A composite capability may keep
  internal operational control. The Toolbox holds no autonomous agent, no
  planner of goals or subgoals, no agentic workflow coordination, no semantic
  replanning and no strategic or managerial decision.
- **All agency is in the core.** Its agents take one of three permanent
  roles, distinguished by the scope of their authority, not by the
  technology they use (an LLM, a symbolic planner or deterministic rules):

  | Role | Specialized by | Responsibility | Planning scope |
  |---|---|---|---|
  | strategic | global goals | Goals, policies and priorities; global coordination; evaluating global results; the decision to replan; the future LLM + planning integration of #619 | the global plan |
  | managerial | domain | Decomposing a delegated goal; a domain subplan; delegating tasks to operational agents or invoking capabilities directly; evaluating results; replanning within the domain; escalating what exceeds its authority | a domain subplan |
  | operational | task | Completing a logically atomic task with the capabilities it is allowed: choosing among alternatives, observing results, recovering local failures, escalating to its manager | a bounded local plan |

- **An operational task is logically atomic, not computationally.** It has
  one verifiable goal, contracted inputs and outputs, allowed capabilities,
  bounded autonomy, a resource budget, completion criteria and escalation
  conditions. The agent may use several capabilities. It does not redefine
  domain goals, change policies, coordinate other subplans, create agents or
  delegate subplans (a first boundary, which #774 may revisit).
- **There is no agent per capability.** A task that a capability performs
  without relevant adaptive decisions is invoked directly by the managerial
  agent. An operational agent is justified by the need for autonomy: choosing
  among alternatives, evaluating results or recovering from failures. Not
  every workflow uses the three levels; the effective hierarchy follows the
  task's complexity.
- **Evidence is not authority.** Managerial and operational agents may use
  support capabilities (comparing candidates, ranking strategies, estimating
  costs, checking constraints, gathering evidence of consistency or
  completion). They compute evidence; the decision to accept an alternative,
  change a subplan or consider a goal satisfied stays with the responsible
  agent in the core. A support capability lives in a pure core library when
  it is a planning or coordination mechanism, and in the Toolbox when it is
  operational processing.
- **Role and lifecycle are separate.** A genuine operational agent can be a
  permanent part of the core. The existing modules of
  `acessilia_core.agents` are operational **legacy** components: they run or
  wrap operations meant for the Toolbox (OCR and semantic extraction,
  document classification, image description, visual adjudication, table
  and formula extraction, multimodal processing).
- **No agent moves to the Toolbox.** A legacy component is decomposed by
  responsibility before it migrates. Model inference, deterministic
  algorithms, technical validation and result transformation become
  non-agentic capabilities. Goal setting and planning stay with the strategic
  core. Subplanning and the choice of strategy stay with the managerial core.
  Semantic evaluation and the decision to replan stay in the core, at the
  scope of the agent that owns them. Contracts and transport belong to the
  core SDK and the shared contracts. For example, a vision agent's inference
  becomes a capability, while the decision to inspect again stays in the
  core.
- **Hierarchical planning stays possible.** Planning need not be monolithic.
  The global plan may delegate domain goals to managerial agents that plan
  subplans, and delegation may recurse with explicit limits on depth, cost,
  time and authority. Delegation contracts, the managerial agents, and the
  comparison of hierarchical with monolithic planning (HTN included) are
  research directions tracked in
  [#774](https://github.com/A11yDevs/acessilia/issues/774) and #619, not
  decisions taken here. #774 compares one level (the strategic agent invokes
  capabilities), two levels (strategic and managerial) and three levels
  (with operational agents). Every semantic step is still planned, at some
  level of the hierarchy, and the strategic core keeps the global logical
  state; the other agents report results and evidence, and do not update it
  in conflicting ways.
- The classification of the existing agents is
  [core-agent-classification.md](../architecture/core-agent-classification.md)
  (#768).
- With `AI_CLIENT=toolbox` (ADR-0012; the production and staging
  deployments), model calls go through the Toolbox, including those a
  strategic agent makes. The default is still `ollama`, and `openrouter` is
  supported. Removing the direct modes is not decided here: it would amend
  ADR-0012 and the configuration. The core interprets model results in the
  context of the plan.
  The Toolbox never decides global goals or replanning.
- Contracts distinguish a capability's result, and the evidence it carries,
  from an agent's decision.

### Planner and coordination are separate

- A `PlanningEngine` interface (#632, PR 3) separates the planner from the
  coordination of the workflow. The internal planner and Fast Downward stay
  interchangeable behind it, and their comparison keeps running.

## Open decisions

This ADR stays `Proposed` until these are closed in review:

- **Fragments per version.** The Toolbox's owners accept serving
  per-capability, per-version fragments from a catalogue snapshot.
- **Result-applied record.** The extension of the ADR-0020 journal and of the
  `execution` checkpoint is reviewed with the checkpoint schema version it
  needs.
- **Cross-component review.** The Toolbox's owners review the planning
  contract (ADR process, step 5). After that, a follow-up pull request sets
  `Accepted`.

## Consequences

- The plan explains every semantic step of the job; availability,
  alternatives and dead ends come from the domain instead of code paths.
  Keeping infrastructure out of the domain keeps it small. This is the
  symbolic baseline for #619.
- The domain grows with the catalogue. Fragment curation, action costs and the
  CI planning fixtures keep it tractable.
- Migration is incremental and follows ADR-0028, method by method. Then the
  three fixed semantic stages become actions, and then the operational
  responsibilities of the legacy agents become non-agentic capabilities. The closed loop does not wait for durable queues
  (#639): synchronous MCP calls are enough.
- Progress indicators are tracked in #735: semantic stages outside the plan
  (3: inspection, extraction, enrichment), plan methods that compute locally
  (14 of 25, ADR-0028), operational agents still in the core.
- Follow-up work, tracked in #735:
  - Toolbox: serve per-capability, per-version PDDL fragments generated from a
    catalogue snapshot (REST and MCP resources).
  - core: compose the domain from those fragments; the policy check for the
    page limit; the journal extension and the result-applied record.
  - core: the managerial layer, delegation contracts and hierarchical
    planning, as research (#774, #619).
- Compliance: the CI planning fixtures; an orchestrator test that every step of
  a job comes from the plan; `tests/test_architecture_layers.py` for model
  clients in the core, and for the classification of every module in
  `acessilia_core.agents` (role and lifecycle).
