"""Canonical English msgids for the nominal-plan executor's error and status strings.

These constants hold the canonical English texts raised or reported by
:class:`backend.core.execution.executor.ExecutorAgent` and
:class:`backend.core.execution.executor.MethodRegistry`. Callers resolve them at
raise/report time through :func:`backend.i18n.t` so the operator-facing text
follows the active locale, while the msgids stay stable English identifiers.
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
#: Status message recorded on a dry-run step; nothing is persisted.
EXE_DRY_RUN_SIMULATED: str = (
    "Simulated execution; no effect was persisted"
)
#: Raised when no method handler is registered for the requested obligation method.
EXE_NO_HANDLER_REGISTERED: str = "No handler registered for {method}"
#: Default status message raised when a handler's result fails validation.
EXE_RESULT_REJECTED: str = "Result rejected by the validator"
#: Raised when a complete-job step leaves selected obligations not satisfied.
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
