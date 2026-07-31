from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from core.agno_support import require_workflow_classes
from core.execution.models import (
    ExecutionReport,
    ExecutionStepResult,
    MethodResult,
)
from core.manifest.models import (
    ObligationAttempt,
    ProcessingManifest,
)
from core.planning.domain_bundle import DomainBundle
from core.planning.models import NominalPlan, PlanStep


MethodHandler = Callable[[ProcessingManifest, str], MethodResult]


class MethodRegistry:
    def __init__(self) -> None:
        self._handlers: dict[str, MethodHandler] = {}

    def register(self, method: str, handler: MethodHandler) -> None:
        if not method:
            raise ValueError("O nome do método não pode ser vazio")
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
    """Executa cada ação nominal em um Step de um Workflow Agno."""

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
                    on_error="fail",
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

    def _validate_binding(
        self,
        plan: NominalPlan,
        manifest: ProcessingManifest,
    ) -> None:
        if plan.domain.name != self.domain.name:
            raise ValueError("O plano usa outro domínio PDDL")
        if plan.domain.version != self.domain.version:
            raise ValueError("A versão do domínio do plano é incompatível")
        if plan.domain.domain_sha256 != self.domain.domain_sha256:
            raise ValueError("O domain.pddl foi alterado depois do planejamento")
        if (
            plan.domain.description_sha256
            != self.domain.description_sha256
        ):
            raise ValueError(
                "A descrição do domínio foi alterada depois do planejamento"
            )
        if plan.manifest_id != manifest.manifest_id:
            raise ValueError("O plano pertence a outro manifesto")
        if plan.manifest_revision != manifest.revision:
            raise ValueError(
                "Revisão divergente entre plano e manifesto: "
                f"{plan.manifest_revision} != {manifest.revision}"
            )
        payload = manifest.model_dump(mode="json", by_alias=True)
        actual_hash = _json_sha256(payload)
        if plan.manifest_sha256 != actual_hash:
            raise ValueError(
                "O manifesto foi alterado depois da geração do plano"
            )
        known = {item.id for item in manifest.obligations}
        unknown = set(plan.selected_obligations) - known
        if unknown:
            raise ValueError(
                f"O plano seleciona obrigações inexistentes: {sorted(unknown)}"
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
                        f"start-job inválido no estado {state.manifest.status}"
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
                        f"Obrigação inexistente: {step.obligation_id}"
                    )
                self._check_obligation_preconditions(
                    obligation,
                    step,
                    state.manifest,
                )
                if state.dry_run:
                    obligation.status = "satisfied"
                    message = "Execução simulada; nenhum efeito foi persistido"
                else:
                    handler = self.registry.get(step.method)
                    if handler is None:
                        raise RuntimeError(
                            f"Nenhum handler registrado para {step.method}"
                        )
                    attempt_started = datetime.now(timezone.utc)
                    result = handler(state.manifest, obligation.id)
                    attempt_completed = datetime.now(timezone.utc)
                    artifact_ids = [artifact.id for artifact in result.artifacts]
                    obligation.attempts.append(
                        ObligationAttempt(
                            method=step.method,
                            status="succeeded" if result.success else "failed",
                            started_at=attempt_started,
                            completed_at=attempt_completed,
                            message=result.message,
                            artifact_ids=artifact_ids,
                        )
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
                            result.message or "Resultado rejeitado pelo validador"
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
                        f"Obrigações selecionadas não satisfeitas: {unsatisfied}"
                    )
                state.manifest.status = "completed"
            else:
                raise ValueError(f"Ação desconhecida: {step.action}")
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
        if manifest.status != "processing":
            raise ValueError("O job não está em processamento")
        if not obligation.selected:
            raise ValueError(f"Obrigação não selecionada: {obligation.id}")
        if obligation.status == "satisfied":
            raise ValueError(f"Obrigação já satisfeita: {obligation.id}")
        if obligation.kind != step.obligation_kind:
            raise ValueError("Tipo da obrigação diverge do plano")
        if step.method not in obligation.admissible_methods:
            raise ValueError(f"Método não admissível: {step.method}")
        tried = {
            attempt.method
            for attempt in obligation.attempts
            if attempt.status in {"failed", "rejected"}
        }
        if step.method in tried:
            raise ValueError(f"Método já tentado: {step.method}")
        by_id = {item.id: item for item in manifest.obligations}
        unsatisfied = [
            dependency
            for dependency in obligation.dependencies
            if by_id[dependency].status != "satisfied"
        ]
        if unsatisfied:
            raise ValueError(
                f"Predecessoras não satisfeitas para {obligation.id}: {unsatisfied}"
            )


def _json_sha256(payload: dict) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
