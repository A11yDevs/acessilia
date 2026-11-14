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
#: PlannerOutcome.validate_outcome: a solved outcome lacks one of plan_file, plan_id, expected_total_cost, step_count or execution_step_count. The English text describes another rule (#530); the msgid is the catalog key, so it changes in its own PR.
MSG_PLANNER_OUTCOME_SOLVED_REQUIRES_FIELDS: str = (
    "A solver outcome marked as ended before execution began cannot carry plan details"
)
#: PlannerOutcome.validate_outcome: a solved outcome whose plan did not pass validation (validation_passed is false).
MSG_PLANNER_OUTCOME_MUST_PASS_VALIDATION: str = ("Marking a planner outcome as solved requires its computed solution to have passed validation")
#: PlannerOutcome.validate_outcome: a solved outcome that also carries error_type or error_message.
MSG_PLANNER_OUTCOME_SOLVED_MUST_NOT_CARRY_ERROR: str = ("Solving a planner outcome cannot also hold recorded error information")
#: PlannerOutcome.validate_outcome: a failed outcome lacks error_type or error_message.
MSG_PLANNER_OUTCOME_FAILED_REQUIRES_ERROR: str = ("A planner outcome marked as failed requires an error type and message")
#: PlannerOutcome.validate_outcome: a failed outcome that records validation_passed as true.
MSG_PLANNER_OUTCOME_FAILED_MUST_NOT_PASS_VALIDATION: str = ("A planner outcome marked as failed cannot simultaneously record successful validation")
#: PlanningComparison.validate_report: the outcomes do not include both the internal planner and Fast Downward.
MSG_COMPARISON_REQUIRES_BOTH_BACKENDS: str = ("Planning comparisons must contain results from both the internal planner and Fast Downward")
#: PlanningComparison.validate_report: an outcome stored under {key} records another planner {backend}.
MSG_COMPARISON_OUTCOME_KEY_MISMATCH: str = ("Outcome key {key} does not match recorded planner backend {backend}")
#: Description of the PlanningComparison JSON schema, resolved with t() when the schema is built; no placeholders.
MSG_PLANNING_COMPARISON_SCHEMA_DESCRIPTION: str = ("Normalized comparison between the internal planner and Fast Downward executions of one planning problem")
#: Description of the NominalPlan JSON schema, resolved with t() when the schema is built; no placeholders. Its pt_BR entry drops the last clause (#530).
MSG_NOMINAL_PLAN_SCHEMA_DESCRIPTION: str = ("Nominal plan derived from the processing manifest and PDDL domain of Acessilia; effects are confirmed only after executed by an executor")
