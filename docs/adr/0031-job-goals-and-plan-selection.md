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
  the current plan: `outside-plan` for a partial selection, or
  `failure-budget-exhausted` for failed work and its dependents excluded by
  discovery policy. Unsatisfied-obligation payloads include the reason when
  present. Selecting the goal in a later plan clears its deferral.
- Checkpoints from 0.3.x remain readable. For obligations still present, the
  executor uses the planning manifest to recover goal flags cleared by the
  older executor. A missing deferral defaults to `None` and is omitted from
  serialization, preserving old manifest hashes and plan bindings. Reasons
  that are present remain part of the persisted manifest and its hash.

## Consequences

The orchestrator no longer needs `_restore_goals`. A plan can finish its
scope while delivery still fails or degrades because another goal remains
open. There is no separate source of truth for goals in runtime services.
This is an additive manifest field under schema 1.1.0; older cores are not
required to read new checkpoints containing it.

`test_job_goals.py` verifies partial plans, later execution, removed goals
and stable legacy hashes. `test_discovery_after_failure_budget.py` verifies
delivery policy, deferral reasons, and current and legacy checkpoint resumes.
