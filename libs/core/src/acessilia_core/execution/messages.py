"""Canonical English msgids of execution: the executor's errors and statuses, and the models' guards.

The ``EXE_*`` constants hold the canonical English texts raised or reported by
:class:`acessilia_core.execution.executor.ExecutorAgent` and
:class:`acessilia_core.execution.executor.MethodRegistry`; the ``MSG_*`` ones at
the end, the validation messages and schema description of
:mod:`acessilia_core.execution.models`. Those came from
``frontend.telegram.messages`` in ADR-0016's step 2 and joined this module,
which execution already had, while planning, which had none, got
``libs/core/src/acessilia_core/planning/messages.py``. Callers resolve them at raise/report
time through :func:`acessilia_core.i18n.t` so the operator-facing text follows
the active locale, while the msgids stay stable English identifiers.
Placeholders such as ``{method}`` are substituted by the caller after lookup.
"""

#: Canonical English msgid raised when MethodRegistry.register receives an empty method name.
EXE_METHOD_NAME_REQUIRED: str = "Method name cannot be empty"

# --- Plan/manifest binding validation ---
#: Raised when a plan references a PDDL domain different from the execution domain.
EXE_PLAN_DIFFERENT_DOMAIN: str = "The plan uses a different PDDL domain"
#: Raised when the plan's PDDL domain version does not match the execution domain.
EXE_PLAN_DOMAIN_VERSION_INCOMPATIBLE: str = (
    "The plan's domain version is incompatible"
)
#: Raised when the domain.pddl payload hash differs from the one captured at planning time.
EXE_DOMAIN_PDDL_CHANGED: str = "domain.pddl was changed after planning"
#: Raised when the domain description hash differs from the one captured at planning time.
EXE_DOMAIN_DESCRIPTION_CHANGED: str = (
    "The domain description was changed after planning"
)
#: Raised when a plan belongs to a manifest other than the one being executed.
EXE_PLAN_OTHER_MANIFEST: str = "The plan belongs to another manifest"
#: Raised when the plan's manifest revision differs from the manifest's current revision.
EXE_PLAN_REVISION_MISMATCH: str = (
    "Divergent revision between plan and manifest: "
    "{plan_revision} != {manifest_revision}"
)
#: Raised when the manifest payload hash differs from the one captured at planning time.
EXE_MANIFEST_CHANGED_AFTER_PLANNING: str = (
    "The manifest was changed after plan generation"
)
#: Raised when a plan selects obligation ids that do not exist in the manifest.
EXE_PLAN_UNKNOWN_OBLIGATIONS: str = (
    "The plan selects non-existent obligations: {unknown}"
)

# --- Step execution ---
#: Raised when a start-job step runs while the manifest is not in an allowed state.
EXE_START_JOB_INVALID_STATE: str = "start-job invalid in state {status}"
#: Raised when an execute-obligation step names an obligation absent from the manifest.
EXE_OBLIGATION_NOT_FOUND: str = "Non-existent obligation: {obligation_id}"
#: A plan step skipped because an earlier step of this execution removed or
#: replaced its obligation (a reclassification reconciled it, #832).
EXE_OBLIGATION_REMOVED: str = (
    "Skipped: obligation {obligation_id} was removed or replaced during this execution"
)
#: A plan step skipped because an earlier step of this execution changed its
#: obligation under the same id: another kind, targets of other types, or the
#: step's method no longer admissible. The replan decides again (#832).
EXE_OBLIGATION_CHANGED: str = (
    "Skipped: obligation {obligation_id} changed during this execution; the replan decides again"
)
#: A plan step skipped because an earlier step of this execution made its
#: obligation depend on open obligations this plan does not run before it:
#: found during the execution, or planned and not run yet. The replan orders
#: them (#832).
EXE_OBLIGATION_WAITS_FOR_OPEN: str = (
    "Skipped: obligation {obligation_id} now depends on {waiting}, still open; the replan orders them"
)
#: Raised when a step's obligation depends on an obligation this execution
#: removed without rewiring its dependents to the replacement (#832). A
#: removal must rewire them; the manifest refuses a dangling dependency.
EXE_DEPENDENCY_REMOVED: str = (
    "Obligation {obligation_id} depends on {missing}, removed during this execution without rewiring its dependents"
)
#: complete-job skipped because the open obligations were all found during
#: this execution or deferred by it (their steps skipped to wait); the replan
#: takes them as roots (#594, #832). ``{open}`` groups their ids by kind.
EXE_DISCOVERED_OBLIGATIONS_OPEN: str = (
    "Skipped: obligations this execution found or deferred are still open: {open}"
)
#: Status message recorded on a dry-run step; nothing is persisted.
EXE_DRY_RUN_SIMULATED: str = (
    "Simulated execution; no effect was persisted"
)
#: Raised when no method handler is registered for the requested obligation method.
EXE_NO_HANDLER_REGISTERED: str = "No handler registered for {method}"
#: Default status message raised when a handler's result fails validation.
EXE_RESULT_REJECTED: str = "Result rejected by the validator"
#: Raised for open obligations in a plan's scope, or for open job goals at delivery.
EXE_COMPLETED_OBLIGATIONS_UNSATISFIED: str = (
    "Selected obligations not satisfied: {unsatisfied}"
)
#: Raised when a workflow step names an action the executor does not know.
EXE_UNKNOWN_ACTION: str = "Unknown action: {action}"

# --- Obligation precondition checks ---
#: Raised when the manifest is not in the processing state during precondition checks.
EXE_JOB_NOT_PROCESSING: str = "The job is not in processing"
#: Raised when the obligation targeted by a step was not selected by the plan.
EXE_OBLIGATION_NOT_SELECTED: str = "Obligation not selected: {obligation_id}"
#: Raised when the obligation targeted by a step was already satisfied.
EXE_OBLIGATION_ALREADY_SATISFIED: str = (
    "Obligation already satisfied: {obligation_id}"
)
#: Raised when the obligation's kind does not match the plan's expectation.
EXE_OBLIGATION_KIND_MISMATCH: str = "Obligation type diverges from the plan"
#: Raised when the requested method is not admissible for the obligation.
EXE_METHOD_NOT_ADMISSIBLE: str = "Method not admissible: {method}"
#: Raised when the requested method was already attempted and rejected.
EXE_METHOD_ALREADY_TRIED: str = "Method already tried: {method}"
#: Raised when unsatisfied dependency obligations remain for the target obligation.
EXE_PREDECESSORS_UNSATISFIED: str = (
    "Unsatisfied predecessors for {obligation_id}: {unsatisfied}"
)

# --- Execution models (acessilia_core.execution.models) ---
#: Requires MethodResult to have been marked validated before claiming success; raise message text for that guard in acessilia_core.execution.models.MethodResult.success_requires_validation domain validation.
MSG_METHOD_RESULT_SUCCESS_REQUIRES_VALIDATION: str = ("A method result claimed as successful must also have passed its validation gate")
#: Duplicate artifact identifier guard across the artifacts mapping on MethodResult, one per unique id expected; raise message text shown to users / developers reading that model's own pydantic validation context.
MSG_METHOD_RESULT_DUPLICATE_ARTIFACT_IDS: str = ("The method result contains duplicate artifact identifiers")
#: Requires a MethodResult carrying a failure kind to be a failed result, not a successful one.
MSG_METHOD_RESULT_FAILURE_KIND_REQUIRES_FAILURE: str = (
    "A method result with a failure kind must not be marked as successful"
)
#: Description of the ExecutionReport JSON schema, resolved with t() when the schema is built; no placeholders.
MSG_EXECUTION_REPORT_SCHEMA_DESCRIPTION: str = ("Report of the execution of a nominal plan over one manifest, with per-step method results and collected artifacts")
