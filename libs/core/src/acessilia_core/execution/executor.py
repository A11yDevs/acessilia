from __future__ import annotations

import hashlib
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, NamedTuple

from acessilia_core.agents.agno_support import require_workflow_classes
from acessilia_core.execution.messages import (
    EXE_COMPLETED_OBLIGATIONS_UNSATISFIED,
    EXE_DEPENDENCY_REMOVED,
    EXE_DISCOVERED_OBLIGATIONS_OPEN,
    EXE_DOMAIN_DESCRIPTION_CHANGED,
    EXE_DOMAIN_PDDL_CHANGED,
    EXE_DRY_RUN_SIMULATED,
    EXE_JOB_NOT_PROCESSING,
    EXE_MANIFEST_CHANGED_AFTER_PLANNING,
    EXE_METHOD_ALREADY_TRIED,
    EXE_METHOD_NAME_REQUIRED,
    EXE_METHOD_NOT_ADMISSIBLE,
    EXE_NO_HANDLER_REGISTERED,
    EXE_OBLIGATION_ALREADY_SATISFIED,
    EXE_OBLIGATION_CHANGED,
    EXE_OBLIGATION_KIND_MISMATCH,
    EXE_OBLIGATION_NOT_FOUND,
    EXE_OBLIGATION_NOT_SELECTED,
    EXE_OBLIGATION_REMOVED,
    EXE_OBLIGATION_WAITS_FOR_OPEN,
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
from acessilia_core.execution.models import (
    ExecutionReport,
    ExecutionStepResult,
    MethodResult,
    ReportMode,
    ReportStatus,
    StepStatus,
)
from acessilia_core.i18n import t
from acessilia_core.logger import logger
from acessilia_core.manifest.models import (
    AttemptStatus,
    Obligation,
    ObligationAttempt,
    ProcessingManifest,
    remap_ids,
    reset_structural_remaps,
    structural_remaps,
)
from acessilia_core.planning.domain_bundle import DomainBundle
from acessilia_core.planning.models import NominalPlan, PlanStep

MethodHandler = Callable[[ProcessingManifest, str], MethodResult]
#: Called before each plan step runs, as ``progress(step, position, total)`` with a
#: 1-based position. It runs on the executor's thread and before the step's
#: handler, so the last call names the step a crash happened in.
StepProgress = Callable[[PlanStep, int, int], None]
#: Called after each plan step with a JSON-ready snapshot of the run, so the
#: caller can persist it and a restart can continue from the next step (#407).
StepCheckpoint = Callable[[dict[str, Any]], None]


@dataclass(frozen=True)
class ExecutionResume:
    """What a previous run of the same plan recorded before it was interrupted.

    ``results`` are the steps already recorded, in plan order; the next step is
    the one after the last result. ``replan_required`` carries the flag a step
    may have set before the interruption, so a resumed run does not lose it.
    """

    manifest: ProcessingManifest
    results: list[ExecutionStepResult]
    replan_required: bool = False
    #: The structural remaps the interrupted run had recorded (#843). A
    #: checkpoint from before 0.3.23 has none: a split before it then reads
    #: as a retarget, and costs one replan.
    remaps: list[dict[str, list[str]]] = field(default_factory=list)


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

    def items(self) -> list[tuple[str, MethodHandler]]:
        """Each method and its handler, in registration order."""
        return list(self._handlers.items())


@dataclass
class _ExecutionState:
    manifest: ProcessingManifest
    dry_run: bool
    results: list[ExecutionStepResult]
    failed_step_index: int | None = None
    replan_required: bool = False
    progress: StepProgress | None = None
    #: The obligations of the manifest the plan was made for, with what made
    #: their method applicable then (``_applicability``). One the working
    #: manifest no longer has was removed during this execution; one it has in
    #: addition was found during it (#594, #832); one whose applicability
    #: changed under the same id is stale.
    planned: dict[str, _Applicability] = field(default_factory=dict)
    selected_obligations: frozenset[str] = field(default_factory=frozenset)


class _SkipStep(Exception):
    """A plan step that no longer applies to the manifest (#832).

    An earlier step of this execution changed the obligations: a
    reclassification removed or replaced the step's obligation, or made it
    depend on an obligation found during the execution. The step is recorded
    ``skipped`` with the reason, not ``failed``: nothing failed, and the
    replan, when one is needed, orders what changed.
    """


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
        *,
        skip: int = 0,
        on_step: StepCheckpoint | None = None,
    ):
        Workflow, Step, _, StepOutput = require_workflow_classes()
        workflow_steps = []
        total = len(plan.steps)
        for position, plan_step in enumerate(plan.steps, start=1):
            # A resumed run keeps the steps already recorded in the checkpoint:
            # their effect is in the manifest and their results in the report.
            if position <= skip:
                continue

            def execute_step(
                _step_input, current: PlanStep = plan_step, position: int = position
            ):
                if state.progress is not None:
                    state.progress(current, position, total)
                result = self._execute_step(current, plan, state)
                if on_step is not None:
                    on_step(_execution_snapshot(plan, state))
                failed = result.status == "failed"
                # A failed obligation does not stop the workflow: the remaining
                # independent obligations still run, and those depending on the
                # failed one fail their own precondition check. complete-job
                # still waits for its scope and goals discovered during execution.
                return StepOutput(
                    content=result.model_dump(mode="json"),
                    success=not failed,
                    error=result.message if failed else None,
                    stop=failed and current.action != "execute-obligation",
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
        progress: StepProgress | None = None,
        resume: ExecutionResume | None = None,
        on_step: StepCheckpoint | None = None,
    ) -> tuple[ProcessingManifest, ExecutionReport]:
        self._validate_binding(plan, manifest)
        if resume is not None and dry_run:
            raise ValueError("A dry run has no checkpoint to resume")
        working, results, replan_required = self._initial_working_state(
            plan, manifest, resume
        )
        replan_required = self._sync_goals(plan, manifest, working) or replan_required
        # The splits and joins of this execution, recorded by
        # ``remap_references`` (#843); a resume continues its own record.
        reset_structural_remaps(working, resume.remaps if resume is not None else [])

        started_at = datetime.now(timezone.utc)
        state = _ExecutionState(
            manifest=working,
            dry_run=dry_run,
            results=results,
            failed_step_index=next(
                (result.index for result in results if result.status == "failed"),
                None,
            ),
            replan_required=replan_required,
            progress=progress,
            planned=_planned_applicability(manifest),
            selected_obligations=frozenset(plan.selected_obligations),
        )
        if len(results) < len(plan.steps):
            workflow = self.build_workflow(
                plan, state, skip=len(results), on_step=on_step
            )
            workflow.run(
                input={
                    "plan_id": plan.plan_id,
                    "manifest_id": manifest.manifest_id,
                    "mode": "dry-run" if dry_run else "live",
                }
            )
        completed_at = datetime.now(timezone.utc)

        returned_manifest, status, revision_after = self._conclude(
            manifest, state, dry_run=dry_run
        )
        report = self._build_report(
            plan,
            manifest,
            state,
            status=status,
            revision_after=revision_after,
            started_at=started_at,
            completed_at=completed_at,
        )
        return returned_manifest, report

    @staticmethod
    def _initial_working_state(
        plan: NominalPlan,
        manifest: ProcessingManifest,
        resume: ExecutionResume | None,
    ) -> tuple[ProcessingManifest, list[ExecutionStepResult], bool]:
        """The manifest, recorded results and replan flag a run starts from."""
        if resume is None:
            return deepcopy(manifest), [], False
        results = list(resume.results)
        indexes = [result.index for result in results]
        if indexes != list(range(len(results))):
            raise ValueError(
                f"A resumed plan expects consecutive step results, got {indexes}"
            )
        if len(results) > len(plan.steps):
            raise ValueError(
                f"A resumed plan has {len(results)} recorded steps, "
                f"but the plan has {len(plan.steps)}"
            )
        return resume.manifest, results, resume.replan_required

    @staticmethod
    def _sync_goals(
        plan: NominalPlan, manifest: ProcessingManifest, working: ProcessingManifest
    ) -> bool:
        """Keep job goals independent of the plan's scope (#883).

        Older execution checkpoints cleared goals outside their plan. The
        planning manifest recovers those flags when resuming if they are
        still recorded there, for existing obligations only. Flags lost
        from both manifests cannot be inferred. A discovered open goal
        still asks for a replan.
        """
        planned = {item.id: item for item in manifest.obligations}
        selected = set(plan.selected_obligations)
        replan_required = False
        for obligation in working.obligations:
            original = planned.get(obligation.id)
            if original is None:
                if obligation.selected and obligation.status != "satisfied":
                    replan_required = True
                continue
            obligation.selected = obligation.selected or original.selected or obligation.id in selected
            if obligation.status == "satisfied" or obligation.id in selected:
                obligation.deferred_reason = None
            elif obligation.selected:
                obligation.deferred_reason = obligation.deferred_reason or "outside-plan"
        return replan_required

    @staticmethod
    def _conclude(
        manifest: ProcessingManifest, state: _ExecutionState, *, dry_run: bool
    ) -> tuple[ProcessingManifest, ReportStatus, int]:
        """The manifest to return, the report status and the revision after the run."""
        status: ReportStatus
        if dry_run:
            status = "failed" if state.failed_step_index is not None else "dry-run-completed"
            return deepcopy(manifest), status, manifest.revision
        returned_manifest = state.manifest
        if state.replan_required:
            status = "replan-required"
        elif state.failed_step_index is not None:
            status = "failed"
        else:
            status = "completed"
        returned_manifest.revision += 1
        return returned_manifest, status, returned_manifest.revision

    @staticmethod
    def _build_report(
        plan: NominalPlan,
        manifest: ProcessingManifest,
        state: _ExecutionState,
        *,
        status: ReportStatus,
        revision_after: int,
        started_at: datetime,
        completed_at: datetime,
    ) -> ExecutionReport:
        mode: ReportMode = "dry-run" if state.dry_run else "live"
        execution_seed = (
            f"{plan.plan_id}:{manifest.manifest_id}:"
            f"{started_at.isoformat()}:{'dry' if state.dry_run else 'live'}"
        )
        return ExecutionReport(
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
            mode=mode,
            status=status,
            replan_required=state.replan_required,
            failed_step_index=state.failed_step_index,
            steps=state.results,
        )

    def _record_obligation_attempt(
        self,
        *,
        obligation,
        method: str,
        started_at: datetime,
        completed_at: datetime,
        status: AttemptStatus,
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
        # Revalidate unchecked copies/mutations, including each step's declared scope.
        NominalPlan.model_validate(plan.model_dump())

    def _execute_step(
        self,
        step: PlanStep,
        plan: NominalPlan,
        state: _ExecutionState,
    ) -> ExecutionStepResult:
        started_at = datetime.now(timezone.utc)
        status: StepStatus = "simulated" if state.dry_run else "succeeded"
        message: str | None = None
        artifact_ids: list[str] = []

        try:
            if step.action == "start-job":
                self._execute_start_job(state)
            elif step.action == "execute-obligation":
                message = self._execute_obligation_step(step, state, artifact_ids)
            elif step.action == "complete-job":
                self._execute_complete_job(state)
            else:
                raise ValueError(
                    t(EXE_UNKNOWN_ACTION).format(action=step.action)
                )
        except _SkipStep as skip:
            status = "skipped"
            message = str(skip)
            logger.info("PDDL: step {} ({}) skipped: {}", step.index, step.action, message)
        except Exception as exc:
            status = "failed"
            message = f"{type(exc).__name__}: {exc}"
            if state.failed_step_index is None:
                state.failed_step_index = step.index
            # The report only reaches the caller as obligation ids, so the cause
            # of each failed step is logged here.
            logger.warning(
                "PDDL: step {} ({}) failed; obligation={} method={}: {}",
                step.index,
                step.action,
                step.obligation_id,
                step.method,
                message,
            )

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
        for obligation in state.manifest.obligations:
            obligation.clear_inactive_deferral()
        state.results.append(result)
        return result

    @staticmethod
    def _execute_start_job(state: _ExecutionState) -> None:
        if state.manifest.status not in {"extracted", "planned"}:
            raise ValueError(
                t(EXE_START_JOB_INVALID_STATE).format(
                    status=state.manifest.status
                )
            )
        state.manifest.status = "processing"

    @staticmethod
    def _execute_complete_job(state: _ExecutionState) -> None:
        # The plan's scope plus goals discovered during this execution.
        # Other job goals remain open for the delivery check, not this plan.
        open_items = [
            item
            for item in state.manifest.obligations
            if item.status != "satisfied"
            and (item.id in state.selected_obligations or (item.selected and item.id not in state.planned))
        ]
        skipped = {result.obligation_id for result in state.results if result.status == "skipped"}
        if open_items and all(
            item.id not in state.planned or item.id in skipped for item in open_items
        ):
            # Not a failure: every open one was found during this execution or
            # had its step skipped to wait for one; the replan takes them as
            # roots (#594, #832). One the plan ran and left open is a failure.
            state.replan_required = True
            raise _SkipStep(
                t(EXE_DISCOVERED_OBLIGATIONS_OPEN).format(open=_by_kind(open_items))
            )
        unsatisfied = [item.id for item in open_items]
        if unsatisfied:
            raise ValueError(
                t(EXE_COMPLETED_OBLIGATIONS_UNSATISFIED).format(
                    unsatisfied=unsatisfied
                )
            )
        state.manifest.status = "completed"

    @staticmethod
    def _find_obligation(state: _ExecutionState, obligation_id: str) -> Obligation:
        for item in state.manifest.obligations:
            if item.id == obligation_id:
                return item
        raise ValueError(
            t(EXE_OBLIGATION_NOT_FOUND).format(obligation_id=obligation_id)
        )

    @classmethod
    def _planned_obligation(cls, state: _ExecutionState, step: PlanStep) -> Obligation:
        """The step's obligation, or a skip when this execution changed it (#832).

        Removed or replaced by a reclassification: the step no longer applies.
        Changed under the same id (another kind, targets of other types,
        another target set, or the step's method no longer admissible): the
        step is stale and the replan decides again. The splits and joins of
        this execution (``remap_references``, recorded on the manifest) are
        applied to the planned targets first, so they alone are not a change:
        the method reads its targets when it runs (``_retargeted``, #843).
        Made to depend on an open obligation this plan does not run before it
        (found during this execution, or planned and not run yet): it waits
        for the replan, which orders the two. A dependency the plan ran and
        left open is still a failure (``_check_obligation_preconditions``).

        A removal rewires the removed obligation's dependents to its
        replacement (``_rewire_removed_dependencies``), and the manifest
        refuses a dangling dependency. One left dangling is a bug of the
        handler, reported as such instead of a ``KeyError``.
        """
        obligation_id = step.obligation_id or ""
        if obligation_id in state.planned and all(
            item.id != obligation_id for item in state.manifest.obligations
        ):
            raise _SkipStep(t(EXE_OBLIGATION_REMOVED).format(obligation_id=obligation_id))
        obligation = cls._find_obligation(state, obligation_id)
        if obligation_id in state.planned and _changed(state, obligation, step):
            state.replan_required = True
            raise _SkipStep(t(EXE_OBLIGATION_CHANGED).format(obligation_id=obligation_id))
        by_id = {item.id: item for item in state.manifest.obligations}
        missing = sorted(set(obligation.dependencies) - by_id.keys())
        if missing:
            raise ValueError(
                t(EXE_DEPENDENCY_REMOVED).format(
                    obligation_id=obligation_id, missing=", ".join(missing)
                )
            )
        ran = {result.obligation_id for result in state.results if result.status != "skipped"}
        waiting = sorted(
            dependency
            for dependency in obligation.dependencies
            if by_id[dependency].status != "satisfied"
            and (dependency not in state.planned or dependency not in ran)
        )
        if waiting:
            state.replan_required = True
            raise _SkipStep(
                t(EXE_OBLIGATION_WAITS_FOR_OPEN).format(
                    obligation_id=obligation_id, waiting=", ".join(waiting)
                )
            )
        return obligation

    def _mark_obligation_failed(
        self,
        obligation: Obligation,
        state: _ExecutionState,
    ) -> None:
        failed_methods = {
            attempt.method
            for attempt in obligation.attempts
            if attempt.status in {"failed", "rejected"}
        }
        alternatives = (
            set(obligation.admissible_methods) & set(self.registry.names())
        ) - failed_methods
        obligation.status = "pending" if alternatives else "failed"
        state.replan_required = state.replan_required or bool(alternatives)

    def _execute_obligation_step(
        self,
        step: PlanStep,
        state: _ExecutionState,
        artifact_ids: list[str],
    ) -> str | None:
        assert step.obligation_id is not None
        assert step.obligation_kind is not None
        assert step.method is not None
        obligation = self._planned_obligation(state, step)
        self._check_obligation_preconditions(obligation, step, state.manifest)
        if state.dry_run:
            obligation.status = "satisfied"
            return t(EXE_DRY_RUN_SIMULATED)
        return self._run_obligation_handler(obligation, step.method, state, artifact_ids)

    def _run_obligation_handler(
        self,
        obligation: Obligation,
        method: str,
        state: _ExecutionState,
        artifact_ids: list[str],
    ) -> str | None:
        handler = self.registry.get(method)
        if handler is None:
            raise RuntimeError(t(EXE_NO_HANDLER_REGISTERED).format(method=method))
        attempt_started = datetime.now(timezone.utc)
        known = {item.id for item in state.manifest.obligations}
        try:
            result = handler(state.manifest, obligation.id)
        except Exception as exc:
            self._record_obligation_attempt(
                obligation=obligation,
                method=method,
                started_at=attempt_started,
                completed_at=datetime.now(timezone.utc),
                status="failed",
                message=f"{type(exc).__name__}: {exc}",
                artifact_ids=[],
            )
            self._mark_obligation_failed(obligation, state)
            raise RuntimeError(f"{type(exc).__name__}: {exc}") from exc

        produced_ids = [artifact.id for artifact in result.artifacts]
        artifact_ids.extend(produced_ids)
        self._record_obligation_attempt(
            obligation=obligation,
            method=method,
            started_at=attempt_started,
            completed_at=datetime.now(timezone.utc),
            status="succeeded" if result.success else "failed",
            message=result.message,
            artifact_ids=produced_ids,
        )
        self._append_new_artifacts(state.manifest, result.artifacts)
        if not result.success or not result.validated:
            self._mark_obligation_failed(obligation, state)
            raise RuntimeError(result.message or t(EXE_RESULT_REJECTED))
        obligation.status = "satisfied"
        self._select_discovered(state, known)
        return result.message

    @staticmethod
    def _append_new_artifacts(
        manifest: ProcessingManifest,
        artifacts: list[Any],
    ) -> None:
        existing = {artifact.id for artifact in manifest.artifacts}
        manifest.artifacts.extend(
            artifact for artifact in artifacts if artifact.id not in existing
        )

    @staticmethod
    def _select_discovered(state: _ExecutionState, known: set[str]) -> None:
        """Select the obligations a successful handler added (#594).

        A handler that adds content derives its processing needs, which no
        plan covers yet. They are selected, so ``complete-job`` waits for them
        and the replan takes them as roots, and one still open asks for that
        replan. The rest of the plan still runs first, as after a failed
        method: its steps stay valid, and the replan budget is not spent on
        work the old plan already had.
        """
        for item in state.manifest.obligations:
            if item.id in known:
                continue
            item.selected = True
            if item.status != "satisfied":
                state.replan_required = True

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


class _Applicability(NamedTuple):
    """What made a step's method applicable to its obligation in the plan's
    manifest (#832, #843)."""

    kind: str
    #: The types of the obligation's targets.
    types: frozenset[str]
    #: The obligation's target ids.
    targets: tuple[str, ...]


def _applicability(manifest: ProcessingManifest, obligation: Obligation) -> _Applicability:
    targets = set(obligation.target_ids)
    types = frozenset(element.type for element in manifest.elements if element.id in targets)
    return _Applicability(obligation.kind, types, tuple(obligation.target_ids))


def _changed(state: _ExecutionState, obligation: Obligation, step: PlanStep) -> bool:
    """Whether a planned obligation changed under its id: another kind,
    targets of other types, another target set (``_retargeted``), or the
    step's method no longer admissible."""
    planned = state.planned[obligation.id]
    now = _applicability(state.manifest, obligation)
    return (
        (now.kind, now.types) != (planned.kind, planned.types)
        or _retargeted(planned.targets, obligation.target_ids, structural_remaps(state.manifest))
        or step.method not in obligation.admissible_methods
    )


def _retargeted(
    planned: tuple[str, ...] | list[str], current: list[str], remaps: list[dict[str, list[str]]]
) -> bool:
    """Whether an obligation's targets are other than its planned ones after
    this execution's splits and joins (#843).

    ``remap_references`` records each split's and join's mapping; composed
    in order over the planned targets, they give the targets the plan's step
    still stands for. Any other change is a retarget, whatever it looks
    like: another element swapped in or added, new or pre-existing, or an
    element dropped without a join. A split then a join composes, and an id
    freed and reused within the execution is not taken for a pre-existing
    element.
    """
    expected = list(planned)
    for mapping in remaps:
        expected = remap_ids(expected, mapping)
    return set(expected) != set(current)


def _planned_applicability(manifest: ProcessingManifest) -> dict[str, _Applicability]:
    return {item.id: _applicability(manifest, item) for item in manifest.obligations}


def _by_kind(obligations: list[Obligation]) -> str:
    """The ids grouped by kind, e.g.
    ``verbalize-formula (o-1, o-2); describe-image (o-3)``."""
    kinds: dict[str, list[str]] = {}
    for item in obligations:
        kinds.setdefault(item.kind, []).append(item.id)
    return "; ".join(
        f"{kind} ({', '.join(sorted(ids))})" for kind, ids in sorted(kinds.items())
    )


def _execution_snapshot(plan: NominalPlan, state: _ExecutionState) -> dict[str, Any]:
    """A JSON-ready snapshot after one plan step, for the job checkpoint (#407)."""
    return {
        "plan_id": plan.plan_id,
        "manifest": state.manifest.model_dump(mode="json", by_alias=True),
        "results": [result.model_dump(mode="json") for result in state.results],
        "replan_required": state.replan_required,
        # The splits and joins so far, so a resume tells them from a retarget (#843).
        "remaps": structural_remaps(state.manifest),
    }


def _json_sha256(payload: dict) -> str:
    from acessilia_core.hashing import json_sha256

    return json_sha256(payload)
