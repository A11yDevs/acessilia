from __future__ import annotations

import hashlib
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from backend.core.agno_support import require_workflow_classes
from backend.core.execution.messages import (
    EXE_COMPLETED_OBLIGATIONS_UNSATISFIED,
    EXE_DRY_RUN_SIMULATED,
    EXE_DOMAIN_DESCRIPTION_CHANGED,
    EXE_DOMAIN_PDDL_CHANGED,
    EXE_JOB_NOT_PROCESSING,
    EXE_MANIFEST_CHANGED_AFTER_PLANNING,
    EXE_METHOD_ALREADY_TRIED,
    EXE_METHOD_NAME_REQUIRED,
    EXE_METHOD_NOT_ADMISSIBLE,
    EXE_NO_HANDLER_REGISTERED,
    EXE_OBLIGATION_ALREADY_SATISFIED,
    EXE_OBLIGATION_KIND_MISMATCH,
    EXE_OBLIGATION_NOT_FOUND,
    EXE_OBLIGATION_NOT_SELECTED,
    EXE_PLAN_DIFFERENT_DOMAIN,
    EXE_PLAN_DOMAIN_VERSION_INCOMPATIBLE,
    EXE_PLAN_OTHER_MANIFEST,
    EXE_PLAN_REVISION_MISMATCH,
    EXE_PLAN_UNKNOWN_OBLIGATIONS,
    EXE_PREDECESSORS_UNSATISFIED,
    EXE_RESULT_REJECTED,
    EXE_START_JOB_INVALID_STATE,
    EXE_UNKNOWN_ACTION,
)
from backend.core.execution.models import (
    ExecutionReport,
    ExecutionStepResult,
    MethodResult,
)
from backend.core.manifest.models import (
    ObligationAttempt,
    ProcessingManifest,
)
from backend.core.planning.domain_bundle import DomainBundle
from backend.core.planning.models import NominalPlan, PlanStep
from backend.i18n import t


MethodHandler = Callable[[ProcessingManifest, str], MethodResult]


class MethodRegistry:
    """Registry mapping obligation method names to their executor handlers."""

    def __init__(self) -> None:
        self._handlers: dict[str, MethodHandler] = {}

    def register(self, method: str, handler: MethodHandler) -> None:
        """Register a handler for a method name.

        Args:
            method (str): Obligation method name to register; must be non-empty.
            handler (MethodHandler): Callable invoked as ``handler(manifest, obligation_id)``.

        Raises:
            ValueError: When ``method`` is empty, carrying the localized method-name-required message.
        """
        if not method:
            raise ValueError(t(EXE_METHOD_NAME_REQUIRED))
        self._handlers[method] = handler

    def get(self, method: str) -> MethodHandler | None:
        return self._handlers.get(method)

    def names(self) -> list[str]:
        return sorted(self._handlers)


@dataclass
class _ExecutionState:
    manifest: ProcessingManifest
    dry_run: bool
    results: list[ExecutionStepResult]
    failed_step_index: int | None = None
    replan_required: bool = False


class ExecutorAgent:
    """Execute each nominal plan action in a Step of an Agno Workflow."""

    def __init__(
        self,
        registry: MethodRegistry | None = None,
        *,
        domain: DomainBundle | None = None,
    ) -> None:
        self.registry = registry or MethodRegistry()
        self.domain = domain or DomainBundle.load()

    def build_workflow(
        self,
        plan: NominalPlan,
        state: _ExecutionState,
    ):
        Workflow, Step, _, StepOutput = require_workflow_classes()
        workflow_steps = []
        for plan_step in plan.steps:
            def execute_step(_step_input, current: PlanStep = plan_step):
                result = self._execute_step(current, plan, state)
                failed = result.status == "failed"
                return StepOutput(
                    content=result.model_dump(mode="json"),
                    success=not failed,
                    error=result.message if failed else None,
                    stop=failed,
                )

            workflow_steps.append(
                Step(
                    name=f"{plan_step.index:04d}-{plan_step.action}",
                    executor=execute_step,
                    max_retries=0,
                )
            )
        return Workflow(
            name="Acessilia Nominal Plan Executor",
            steps=workflow_steps,
            telemetry=False,
        )

    def execute(
        self,
        plan: NominalPlan,
        manifest: ProcessingManifest,
        *,
        dry_run: bool = False,
    ) -> tuple[ProcessingManifest, ExecutionReport]:
        self._validate_binding(plan, manifest)
        working = deepcopy(manifest)
        for obligation in working.obligations:
            obligation.selected = obligation.id in set(plan.selected_obligations)

        started_at = datetime.now(timezone.utc)
        state = _ExecutionState(
            manifest=working,
            dry_run=dry_run,
            results=[],
        )
        workflow = self.build_workflow(plan, state)
        workflow.run(
            input={
                "plan_id": plan.plan_id,
                "manifest_id": manifest.manifest_id,
                "mode": "dry-run" if dry_run else "live",
            }
        )
        completed_at = datetime.now(timezone.utc)

        if dry_run:
            returned_manifest = deepcopy(manifest)
            status = "dry-run-completed"
            revision_after = manifest.revision
        else:
            returned_manifest = state.manifest
            if state.replan_required:
                status = "replan-required"
            elif state.failed_step_index is not None:
                status = "failed"
            else:
                status = "completed"
            returned_manifest.revision += 1
            revision_after = returned_manifest.revision

        execution_seed = (
            f"{plan.plan_id}:{manifest.manifest_id}:"
            f"{started_at.isoformat()}:{'dry' if dry_run else 'live'}"
        )
        report = ExecutionReport(
            execution_id=(
                "execution-"
                + hashlib.sha256(execution_seed.encode()).hexdigest()[:16]
            ),
            plan_id=plan.plan_id,
            manifest_id=manifest.manifest_id,
            manifest_revision_before=manifest.revision,
            manifest_revision_after=revision_after,
            started_at=started_at,
            completed_at=completed_at,
            mode="dry-run" if dry_run else "live",
            status=status,
            replan_required=state.replan_required,
            failed_step_index=state.failed_step_index,
            steps=state.results,
        )
        return returned_manifest, report

    def _record_obligation_attempt(
        self,
        *,
        obligation,
        method: str,
        started_at: datetime,
        completed_at: datetime,
        status: str,
        message: str | None,
        artifact_ids: list[str],
    ) -> None:
        obligation.attempts.append(
            ObligationAttempt(
                method=method,
                status=status,
                started_at=started_at,
                completed_at=completed_at,
                message=message,
                artifact_ids=artifact_ids,
            )
        )

    def _validate_binding(
        self,
        plan: NominalPlan,
        manifest: ProcessingManifest,
    ) -> None:
        """Validate that the plan is bound to this manifest, domain, and revision.

        Args:
            plan (NominalPlan): Plan whose domain name/version/hashes and manifest
                id/revision/sha are checked against the execution domain and manifest.
            manifest (ProcessingManifest): Manifest whose identity and payload hash must
                match what the plan captured at planning time.

        Raises:
            ValueError: When any binding check fails, carrying the localized message.
        """
        if plan.domain.name != self.domain.name:
            raise ValueError(t(EXE_PLAN_DIFFERENT_DOMAIN))
        if plan.domain.version != self.domain.version:
            raise ValueError(t(EXE_PLAN_DOMAIN_VERSION_INCOMPATIBLE))
        if plan.domain.domain_sha256 != self.domain.domain_sha256:
            raise ValueError(t(EXE_DOMAIN_PDDL_CHANGED))
        if (
            plan.domain.description_sha256
            != self.domain.description_sha256
        ):
            raise ValueError(t(EXE_DOMAIN_DESCRIPTION_CHANGED))
        if plan.manifest_id != manifest.manifest_id:
            raise ValueError(t(EXE_PLAN_OTHER_MANIFEST))
        if plan.manifest_revision != manifest.revision:
            raise ValueError(
                t(EXE_PLAN_REVISION_MISMATCH).format(
                    plan_revision=plan.manifest_revision,
                    manifest_revision=manifest.revision,
                )
            )
        payload = manifest.model_dump(mode="json", by_alias=True)
        actual_hash = _json_sha256(payload)
        if plan.manifest_sha256 != actual_hash:
            raise ValueError(t(EXE_MANIFEST_CHANGED_AFTER_PLANNING))
        known = {item.id for item in manifest.obligations}
        unknown = set(plan.selected_obligations) - known
        if unknown:
            raise ValueError(
                t(EXE_PLAN_UNKNOWN_OBLIGATIONS).format(unknown=sorted(unknown))
            )

    def _execute_step(
        self,
        step: PlanStep,
        plan: NominalPlan,
        state: _ExecutionState,
    ) -> ExecutionStepResult:
        started_at = datetime.now(timezone.utc)
        status = "simulated" if state.dry_run else "succeeded"
        message: str | None = None
        artifact_ids: list[str] = []

        try:
            if step.action == "start-job":
                if state.manifest.status not in {"extracted", "planned"}:
                    raise ValueError(
                        t(EXE_START_JOB_INVALID_STATE).format(
                            status=state.manifest.status
                        )
                    )
                state.manifest.status = "processing"
            elif step.action == "execute-obligation":
                assert step.obligation_id is not None
                assert step.obligation_kind is not None
                assert step.method is not None
                obligation = next(
                    (
                        item
                        for item in state.manifest.obligations
                        if item.id == step.obligation_id
                    ),
                    None,
                )
                if obligation is None:
                    raise ValueError(
                        t(EXE_OBLIGATION_NOT_FOUND).format(
                            obligation_id=step.obligation_id
                        )
                    )
                self._check_obligation_preconditions(
                    obligation,
                    step,
                    state.manifest,
                )
                if state.dry_run:
                    obligation.status = "satisfied"
                    message = t(EXE_DRY_RUN_SIMULATED)
                else:
                    handler = self.registry.get(step.method)
                    if handler is None:
                        raise RuntimeError(
                            t(EXE_NO_HANDLER_REGISTERED).format(
                                method=step.method
                            )
                        )
                    attempt_started = datetime.now(timezone.utc)
                    try:
                        result = handler(state.manifest, obligation.id)
                    except Exception as exc:
                        attempt_completed = datetime.now(timezone.utc)
                        self._record_obligation_attempt(
                            obligation=obligation,
                            method=step.method,
                            started_at=attempt_started,
                            completed_at=attempt_completed,
                            status="failed",
                            message=f"{type(exc).__name__}: {exc}",
                            artifact_ids=[],
                        )
                        alternatives = set(obligation.admissible_methods) - {
                            attempt.method
                            for attempt in obligation.attempts
                            if attempt.status in {"failed", "rejected"}
                        }
                        obligation.status = "pending" if alternatives else "failed"
                        state.replan_required = bool(alternatives)
                        raise RuntimeError(
                            f"{type(exc).__name__}: {exc}"
                        ) from exc

                    attempt_completed = datetime.now(timezone.utc)
                    artifact_ids = [artifact.id for artifact in result.artifacts]
                    self._record_obligation_attempt(
                        obligation=obligation,
                        method=step.method,
                        started_at=attempt_started,
                        completed_at=attempt_completed,
                        status="succeeded" if result.success else "failed",
                        message=result.message,
                        artifact_ids=artifact_ids,
                    )
                    existing_artifacts = {
                        artifact.id for artifact in state.manifest.artifacts
                    }
                    state.manifest.artifacts.extend(
                        artifact
                        for artifact in result.artifacts
                        if artifact.id not in existing_artifacts
                    )
                    if not result.success or not result.validated:
                        alternatives = set(obligation.admissible_methods) - {
                            attempt.method
                            for attempt in obligation.attempts
                            if attempt.status in {"failed", "rejected"}
                        }
                        obligation.status = "pending" if alternatives else "failed"
                        state.replan_required = bool(alternatives)
                        raise RuntimeError(
                            result.message or t(EXE_RESULT_REJECTED)
                        )
                    obligation.status = "satisfied"
                    message = result.message
            elif step.action == "complete-job":
                selected = {
                    item.id: item
                    for item in state.manifest.obligations
                    if item.id in set(plan.selected_obligations)
                }
                unsatisfied = [
                    item.id
                    for item in selected.values()
                    if item.status != "satisfied"
                ]
                if unsatisfied:
                    raise ValueError(
                        t(EXE_COMPLETED_OBLIGATIONS_UNSATISFIED).format(
                            unsatisfied=unsatisfied
                        )
                    )
                state.manifest.status = "completed"
            else:
                raise ValueError(
                    t(EXE_UNKNOWN_ACTION).format(action=step.action)
                )
        except Exception as exc:
            status = "failed"
            message = f"{type(exc).__name__}: {exc}"
            state.failed_step_index = step.index

        result = ExecutionStepResult(
            index=step.index,
            action=step.action,
            status=status,
            obligation_id=step.obligation_id,
            method=step.method,
            started_at=started_at,
            completed_at=datetime.now(timezone.utc),
            message=message,
            artifact_ids=artifact_ids,
        )
        state.results.append(result)
        return result

    @staticmethod
    def _check_obligation_preconditions(
        obligation,
        step: PlanStep,
        manifest: ProcessingManifest,
    ) -> None:
        """Check that an obligation may be executed by the given plan step.

        Args:
            obligation: Obligation instance targeted by the step (no type spec; duck-typed).
            step (PlanStep): Nominal plan step whose action, method, and obligation id are checked.
            manifest (ProcessingManifest): Manifest providing job status and obligation lookups.

        Raises:
            ValueError: When any precondition fails, carrying the localized message.
        """
        if manifest.status != "processing":
            raise ValueError(t(EXE_JOB_NOT_PROCESSING))
        if not obligation.selected:
            raise ValueError(
                t(EXE_OBLIGATION_NOT_SELECTED).format(
                    obligation_id=obligation.id
                )
            )
        if obligation.status == "satisfied":
            raise ValueError(
                t(EXE_OBLIGATION_ALREADY_SATISFIED).format(
                    obligation_id=obligation.id
                )
            )
        if obligation.kind != step.obligation_kind:
            raise ValueError(t(EXE_OBLIGATION_KIND_MISMATCH))
        if step.method not in obligation.admissible_methods:
            raise ValueError(
                t(EXE_METHOD_NOT_ADMISSIBLE).format(method=step.method)
            )
        tried = {
            attempt.method
            for attempt in obligation.attempts
            if attempt.status in {"failed", "rejected"}
        }
        if step.method in tried:
            raise ValueError(
                t(EXE_METHOD_ALREADY_TRIED).format(method=step.method)
            )
        by_id = {item.id: item for item in manifest.obligations}
        unsatisfied = [
            dependency
            for dependency in obligation.dependencies
            if by_id[dependency].status != "satisfied"
        ]
        if unsatisfied:
            raise ValueError(
                t(EXE_PREDECESSORS_UNSATISFIED).format(
                    obligation_id=obligation.id,
                    unsatisfied=unsatisfied,
                )
            )


def _json_sha256(payload: dict) -> str:
    from backend.core.hashing import json_sha256

    return json_sha256(payload)
