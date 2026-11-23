# The projection of observed state into PDDL (#640, PR 1)

You can also read this documentation in **Brazilian Portuguese**: [português brasileiro](pddl-state-projection.pt-br.md)

[ADR-0029](../adr/0029-symbolic-core-every-step-planned.md) compiles each
planning problem from observed state: the manifest's facts, the obligations,
the results already recorded and one catalogue snapshot. This page documents
what `PddlProblemCompiler.compile` (`planning/pddl_processor.py`) projects
today, for domain v2.3, and what is still missing.
`libs/core/tests/test_pddl_state_projection.py` has one test per rule, so a
change to the projection is a visible diff.

## Inputs

`compile(manifest, *, selected_roots=None, unavailable_methods=())`. The
orchestrator calls it through the `PlanningEngine` (#744) with a
`PlanningProblem`:

- `manifest`: the processing manifest, as observed so far;
- `selected_roots`: the obligations to plan, or `None` (see below);
- `unavailable_methods`: the methods the plan must not use. These are the
  methods without a registered handler, plus, when the availability gate
  enforces, the methods whose Toolbox capability or provider is missing from
  the catalogue snapshot.

## Rules

| Observed state | PDDL | Notes |
|---|---|---|
| Manifest status `extracted` or `planned` | `(queued)` | The plan starts with `start-job` |
| Any other status (`processing`, `failed`) | `(processing)` | A replan continues the job |
| Manifest status `completed` | refused (`ValueError`) | A completed job is not planned |
| — | `(= (total-cost) 0)`, goal `(completed)`, metric `minimize (total-cost)` | Every problem |
| Roots: `selected_roots`; without them, the obligations marked `selected`; without those, every obligation not `satisfied` | — | An unknown root is refused |
| The roots and their transitive `dependencies` | one `obligation` object and `(selected o)` each | Obligations outside the closure are not projected at all |
| Obligation `kind` | `(kind-of o k)`, one `obligationkind` object | |
| Status `satisfied` | `(satisfied o)` | |
| Any other status (`candidate`, `pending`, `in_progress`, `failed`) | `(pending o)` | A `failed` obligation with an untried method can still be planned |
| `dependencies` | `(depends-on o predecessor)` | |
| Each admissible method | `(supports m k)`, `(admissible m o)` | `supports` comes from the manifest's admissible methods, not from a catalogue |
| `method_costs[m]` | `(= (execution-cost m o) cost)` | 50 when the manifest declares no cost |
| A method not in `unavailable_methods` | `(available m)` | Per method, not per capability or provider |
| An attempt `failed` or `rejected` | `(tried o m)` | A `succeeded` attempt is not projected; its result is the obligation's status. A `failed` attempt rules the method out for that obligation whatever the cause (see below) |
| Ids, kinds and method names | PDDL symbols (`[a-z][a-z0-9-]*`) | The projection keeps both directions of the mapping |

Duplicated facts are emitted once. The problem does not depend on the order
of the obligations or of their methods in the manifest, and distinct ids that
normalize to the same symbol get distinct symbols (a hash suffix).

An empty root set, or a manifest without obligations, projects no obligation:
the plan is `start-job`, `complete-job`.

## What is not projected

- The document itself: elements, text, targets, observations and artifacts
  stay in the manifest. The plan names obligations and methods only.
- Obligations outside the selected closure.
- Successful attempts, and the results of methods, except through the
  obligation's status.

## Checks

The compiler refuses a problem it cannot plan, before the planner runs:

- **Causal state.** A satisfied obligation with an unsatisfied predecessor.
  The manifest model refuses this state too; the compiler checks again
  because a replan changes the manifest in place.
- **Methods.** A pending obligation with no method that is admissible,
  available and not tried.
- **Catalogue v2.3.** For a kind in the v2.3 catalogue, admissible methods
  outside it, or a method without a cost.
- **Unknown unavailable methods.** An unavailable method that the manifest
  does not declare: a typo, not a capability gap.
- **Not yet: cycles and unknown dependencies.** The manifest model refuses
  them, but one introduced by a replan compiles: the internal planner refuses
  a cycle when ordering, Fast Downward finds no plan, and an unknown
  dependency raises a bare `KeyError`. The compiler should refuse both
  ([#783](https://github.com/A11yDevs/acessilia/issues/783)).
- **The rendered problem.** `PddlProblemValidator` checks it against the
  projection.

## Identity

- `CompiledProblem.sha256` is the hash of the problem text. It changes
  exactly when the projected state changes, and the plan records it
  (`problem_sha256`). The coordinator checks it since #744.
- `manifest_sha256` is the hash of the whole manifest, including what is not
  projected.
- The two are different identities. Two manifests that differ only outside
  the projection (an element's text, an observation) produce the same
  problem, so `problem_sha256` is the identity of the planning state, never
  of the document state. Checkpoints, delegation contracts and replanning
  keep both.

## Known limitation: what `tried` means

`tried` comes from any `failed` or `rejected` attempt, so a method that
failed for a transient reason (a timeout, a provider down, an infrastructure
error) is ruled out for that obligation like one that could not satisfy it.
The closed loop needs to tell apart:

- a semantic failure: the method ran and did not satisfy the obligation;
- a rejection: the result did not meet the criteria;
- a transient failure: timeout, unavailable provider, infrastructure;
- a permanent failure: the capability is incompatible or cannot run the
  operation.

Not all of them should stop a retry of the same method. This belongs to the
result contracts, the execution journal and the replanning rules of #640
(PRs 3 and 4). This page documents today's behaviour.

## What ADR-0029 still asks for

| ADR-0029 | Today | Next |
|---|---|---|
| Capability and provider availability are predicates of the problem | The gate turns them into `unavailable_methods`, outside the problem, and only in `enforce` mode | PR 1, second part: the catalogue snapshot as facts (requirements per method, offered capabilities and providers), and availability derived in the domain. This needs a new domain version |
| `toolbox_gate` is reduced to reporting | It decides `unavailable_methods` | #640, PR 2, after the predicates |
| Operational actions are bound to a capability id and exact version | Methods name local handlers | #640, PR 2, with the domain fragments |
| A result updates the state once per `operation_id` | The manifest's statuses and attempts | #640, PR 3, with the journal of ADR-0020 |
| Inspection, extraction and enrichment are actions | They run before planning | #640, PR 2 |
