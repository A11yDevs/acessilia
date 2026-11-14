"""Canonical English msgids of the planning models' validation errors and schema descriptions.

``backend.core.planning.models`` raises these (resolved with
:func:`backend.core.i18n.t` when it raises) and uses the schema descriptions in
its JSON schemas. They lived in ``frontend.telegram.messages`` until ADR-0016's
step 2 gave the core its own messages; the msgids are unchanged.
"""

from __future__ import annotations

#: PlanStep.validate_parameters failing on an execute-obligation action missing any of obligation_id / obligation_kind / method.
MSG_EXECUTE_OBLIGATION_MISSING_FIELDS: str = ("The execute-obligation action requires obligation_id, obligation_kind and method")
#: PlanStep.validate_parameters failing when a non-execution plan step still carries execution parameter values for {action}.
MSG_ACTION_REJECTS_EXECUTION_PARAMETERS: str = ("{action} does not accept obligation or method parameters")
#: NominalPlan.validate_plan failure when step indices are not zero-based and contiguous whole numbers in order.
MSG_PLAN_INDICES_CONSECUTIVE_FROM_ZERO: str = ("Plan step indices must be contiguous whole numbers starting at zero")
#: NominalPlan.validate_plan failure when the final plan step is missing the mandatory complete-job termination action for a nominal plan.
MSG_NOMINAL_PLAN_MUST_END_COMPLETE_JOB: str = ("A nominal plan must end with the complete-job action")
#: NominalPlan.validate_plan failure comparing declared expected_total_cost field {declared} to summed per-step expected cost total of {calculated} in an unequal check for the two values.
MSG_EXPECTED_TOTAL_COST_MISMATCH: str = ("Declared expected_total_cost={declared}; plan steps sum to expected cost {calculated}")
#: NominalPlan.validate_plan failure when a planned execute-obligation step has no corresponding entry in selected_obligations.
MSG_PLAN_CONTAINS_UNSELECTED_OBLIGATION: str = ("A nominal plan contains an obligation that was not selected")
#: PlannerOutcome validate_outcome requiring all plan content fields to be present for status==solved results per {message} below at the raise site in planning/models.py in the code change accompanying this constant. Used for a solved result lacking at least one of plan file, identifier or statistics content.
MSG_PLANNER_OUTCOME_SOLVED_REQUIRES_FIELDS: str = (
    "A solver outcome marked as ended before execution began cannot carry plan details"
)
#: Outcome validation requiring the recorded run to have been validated and accepted after solving for a result that claims solved status without successful validator pass recorded alongside it.
MSG_PLANNER_OUTCOME_MUST_PASS_VALIDATION: str = ("Marking a planner outcome as solved requires its computed solution to have passed validation")
#: Prohibiting any error record field from being present on an otherwise-validated successful solver run result in PlannerOutcome validate_outcome for status==solved branches.
MSG_PLANNER_OUTCOME_SOLVED_MUST_NOT_CARRY_ERROR: str = ("Solving a planner outcome cannot also hold recorded error information")
#: Require both fields present when recording a run that reported no solution found at PlannerOutlet's validation site in Planning/Model.Py for a result claiming failed status without any diagnostic content attached at all.
MSG_PLANNER_OUTCOME_FAILED_REQUIRES_ERROR: str = ("A planner outcome marked as failed requires an error type and message")
#: Forbid marking computed results both validated-and-passed while simultaneously flagged as having failed validation when the run finished solving successfully in a failed-status branch check on the same PlannerOutcome record during validate_outcome.
MSG_PLANNER_OUTCOME_FAILED_MUST_NOT_PASS_VALIDATION: str = ("A planner outcome marked as failed cannot simultaneously record successful validation")
#: Requires both planned execution backends listed in outcomes mapping for PlanningComparison.validate_report domain-level consistency check comparing planner identities against recorded backend keys; raise message text shown to users / developers reading the generated JSON comparison result report body.
MSG_COMPARISON_REQUIRES_BOTH_BACKENDS: str = ("Planning comparisons must contain results from both the internal planner and Fast Downward")
#: Outcome key mismatch guard on each backend, result pair in that mapping for {key} expecting {backend_name}; raise message text shown to users / developers reading validation context after a comparison report builds successfully with divergent identifiers attached elsewhere in its metadata fields as well.
MSG_COMPARISON_OUTCOME_KEY_MISMATCH: str = ("Outcome key {key} does not match recorded planner backend {backend}")
#: A normalized description for the planning-comparison JSON schema document, localized alongside every other user-visible string in this branch's i18n effort so tooling inspecting or rendering schema metadata can rely on catalog-driven localization rather than hardcoded strings; variable substituted at call time via t() like all other part-6 entries.
MSG_PLANNING_COMPARISON_SCHEMA_DESCRIPTION: str = ("Normalized comparison between the internal planner and Fast Downward executions of one planning problem")
#: A normalized description for the nominal-plan JSON schema document, localized so tooling inspecting or rendering its metadata reads catalog-driven text; variable substituted at call time via t() like all other part-6 entries.
MSG_NOMINAL_PLAN_SCHEMA_DESCRIPTION: str = ("Nominal plan derived from the processing manifest and PDDL domain of Acessilia; effects are confirmed only after executed by an executor")
