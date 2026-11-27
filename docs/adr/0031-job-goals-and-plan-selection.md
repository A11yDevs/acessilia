# 0031. Job goals outlive the selection of a plan

Brazilian Portuguese: [português brasileiro](0031-job-goals-and-plan-selection.pt-br.md).

- **Status:** Accepted
- **Date:** 2026-11-26
- **Components:** core
- **Issues:** [#883](https://github.com/A11yDevs/acessilia/issues/883), [#640](https://github.com/A11yDevs/acessilia/issues/640)

## Context

An obligation's `selected` flag served both as a job goal and as membership
in the current plan. A discovery plan after the failure budget is exhausted
serves only independent work. Clearing the other goals hid failures from
the delivery check. #882 restored those flags after each run, but execution
checkpoints still recorded the temporary loss of goals.

## Decision

- `Obligation.selected` records a job goal. Executing a plan must not clear
  this flag on goals outside its scope. A successful handler's discovered
  obligations become goals as before; removed obligations stay removed.
- `NominalPlan.selected_obligations` records the current plan's scope,
  including dependencies. `complete-job` checks this scope and newly
  discovered goals. The final delivery check judges all open job goals,
  even when the last plan completed. Existing criticality and cache policies
  continue to apply.
- An optional `Obligation.deferred_reason` records why a goal is outside
  a plan: `outside-plan` records exclusion from its scope, including exhausted
  work and goals blocked by exhausted dependencies; it promises no future
  eligibility. `failure-budget-exhausted` is more specific: the goal is
  ordinarily replannable but discovery policy excludes it or its failed
  predecessor. Exhaustion alone never gets this budget reason.
  `replan_roots` recomputes reasons at each policy decision, even with no
  roots. Between decisions the most recent explanation persists, including
  across resumes. Selecting or satisfying the goal clears it. Read and
  serialization boundaries normalize reasons on satisfied/non-goal obligations;
  legacy unselected failures remain open goals for compatibility.
- Checkpoints without the new field remain readable. For obligations still
  present, the executor can recover cleared flags **only if the planning
  manifest retains them** (as in the real 0.3.26 fixture). If both manifests
  already lost a goal, it is indistinguishable from intentionally unselected
  work; this PR cannot reconstruct it. Recovery depends on recorded state,
  not the package version alone. A missing deferral is omitted from
  serialization, preserving old manifest hashes and plan bindings. Reasons
  that are present remain part of the persisted manifest and its hash.

## Consequences

The orchestrator no longer needs `_restore_goals`. A plan can finish its
scope while delivery still fails or degrades because another goal remains
open. There is no separate source of truth for goals in runtime services.
Exclusion from a partial plan never cancels a goal. `selected=False` alone
is not a cancellation transition: a resume can recover the planning flag.
An obsolete obligation can still be removed. Explicit persisted cancellation
and any rename of `selected` are follow-up [#909](https://github.com/A11yDevs/acessilia/issues/909).

### Narrow contract-versioning exception

This decision deliberately extends the core's processing-manifest:1.1.0
without changing its id, an exception to [ADR-0007](0007-manifest-model-and-mathml-conversion.md)
and audit finding A1's versioning/conformance requirements. Scope: optional
core planning metadata, omitted when absent, preserving historical plan
hashes. The core validator owns this extension; the Toolbox schema and SDK's
generated `MANIFEST_RULE` remain strict and do not accept `deferred_reason`.
A core checkpoint carrying it is not a Toolbox structured-document payload;
older cores are not required to read it.

Owner: core maintainers, coordinating with SDK/Toolbox contract owners.
Exit criterion: give the core planning envelope a distinct versioned contract
or migration, explicit adapters, and cross-contract tests in
[#908](https://github.com/A11yDevs/acessilia/issues/908). This exception does
not authorize further silent schema divergence.

`test_job_goals.py` verifies partial plans, later execution, removed goals
and a real 0.3.26 plan/execution fixture with provenance and its original
hash. `test_discovery_after_failure_budget.py` verifies
delivery policy, deferral reasons, and current and legacy checkpoint resumes.
