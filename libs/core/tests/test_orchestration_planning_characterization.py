"""Characterization tests for the helpers of PR 11 (#612): comparison, executor, PDDL validation, handler contract.

The orchestrator, enrichment-stage and agent flows stay pinned by the existing
``test_execute_flow``, ``test_picture_enrichment_flow``, ``test_table_enrichment_flow``
and ``test_ai_client`` suites; these tests pin the pure helpers extracted from
the functions that were above the complexity limit.
"""

from __future__ import annotations

import hashlib
import inspect
from dataclasses import replace

import pytest
from pddl_support import NOW, build_element, build_manifest, build_obligation

from acessilia_core.config import CoreConfig
from acessilia_core.execution.executor import (
    ExecutionResume,
    ExecutorAgent,
    _ExecutionState,
)
from acessilia_core.execution.models import ExecutionStepResult
from acessilia_core.manifest.models import ProcessingManifest
from acessilia_core.pipeline.handlers.registry import (
    _classify_parameter,
    _positional_problems,
)
from acessilia_core.planning.comparison import _compare_plans
from acessilia_core.planning.domain_bundle import DomainBundle
from acessilia_core.planning.models import DomainIdentity, NominalPlan, PlanStep
from acessilia_core.planning.pddl_processor import (
    PddlProblemCompiler,
    _validate_action_sequence,
)
from acessilia_core.ports import RunPorts


def _plan(steps: list[PlanStep], cost: int | None = None) -> NominalPlan:
    full_steps = [
        step.model_copy(update={"index": idx}) for idx, step in enumerate(steps)
    ]
    if not full_steps or full_steps[-1].action != "complete-job":
        full_steps.append(PlanStep(index=len(full_steps), action="complete-job"))
    total_cost = (
        sum(step.expected_cost for step in full_steps) if cost is None else cost
    )
    return NominalPlan(
        plan_id="plan-1",
        generated_at=NOW,
        manifest_id="manifest-actionability",
        manifest_revision=1,
        manifest_sha256="a" * 64,
        planner="heuristic",
        domain=DomainIdentity(
            name="acessilia",
            version="2.3",
            domain_sha256="b" * 64,
            description_sha256="c" * 64,
        ),
        problem_name="prob-1",
        problem_sha256="d" * 64,
        selected_obligations=["o-1", "o-2"],
        expected_total_cost=total_cost,
        steps=full_steps,
    )


def _execute(index: int, obligation_id: str, method: str, cost: int = 10) -> PlanStep:
    return PlanStep(
        index=index,
        action="execute-obligation",
        obligation_id=obligation_id,
        obligation_kind="describe-image",
        method=method,
        expected_cost=cost,
    )


class TestComparePlansCharacterization:
    def test_without_both_plans_the_verdict_is_inconclusive(self) -> None:
        details = _compare_plans(_plan([]), None)
        assert details.verdict == "inconclusive"
        assert details.both_solved is False
        assert _compare_plans(None, None).verdict == "inconclusive"

    def test_identical_equivalent_and_different_verdicts(self) -> None:
        a = _execute(0, "o-1", "m1")
        b = _execute(1, "o-2", "m2")
        base = _compare_plans(_plan([a, b]), _plan([a, b]))
        assert base.verdict == "identical"
        assert base.notes == []

        reordered = _compare_plans(_plan([a, b]), _plan([b, a]))
        assert reordered.verdict == "equivalent"
        assert reordered.same_action_sequence is False
        assert reordered.same_action_multiset is True
        assert len(reordered.notes) == 1

        different = _compare_plans(
            _plan([a, b]), _plan([a, _execute(1, "o-2", "m3", cost=15)])
        )
        assert different.verdict == "different"
        assert different.same_expected_total_cost is False
        assert different.cost_delta_fast_downward_minus_internal == 5
        assert different.notes == []

        same_cost_different = _compare_plans(
            _plan([a, b]), _plan([a, _execute(1, "o-2", "m3", cost=10)])
        )
        assert same_cost_different.verdict == "different"
        assert same_cost_different.same_expected_total_cost is True
        assert len(same_cost_different.notes) == 1
        assert same_cost_different.notes != reordered.notes


class TestExecutorHelpersCharacterization:
    def _manifest(self) -> ProcessingManifest:
        return build_manifest(
            [build_element("e1", "picture", text="")],
            [build_obligation("describe-image", ["e1"], ["vision-description"])],
        )

    def test_resume_state_must_hold_consecutive_results_within_the_plan(self) -> None:
        manifest = self._manifest()
        plan = _plan([_execute(0, "o-1", "m1")])

        def result(index: int) -> ExecutionStepResult:
            return ExecutionStepResult(
                index=index,
                action="start-job",
                status="succeeded",
                started_at=NOW,
                completed_at=NOW,
            )

        with pytest.raises(ValueError, match="consecutive step results"):
            ExecutorAgent._initial_working_state(
                plan, manifest, ExecutionResume(manifest=manifest, results=[result(1)])
            )
        with pytest.raises(ValueError, match="recorded steps"):
            ExecutorAgent._initial_working_state(
                plan,
                manifest,
                ExecutionResume(
                    manifest=manifest,
                    results=[result(0), result(1), result(2)],
                ),
            )
        working, results, replan = ExecutorAgent._initial_working_state(
            plan, manifest, None
        )
        assert working is not manifest and results == [] and replan is False

        resumed = ExecutionResume(
            manifest=manifest, results=[result(0)], replan_required=True
        )
        resumed_working, resumed_results, resumed_replan = (
            ExecutorAgent._initial_working_state(plan, manifest, resumed)
        )
        assert resumed_working is manifest
        assert resumed_results == [result(0)]
        assert resumed_replan is True

    def test_conclude_and_build_report_pin_status_revision_and_seed(self) -> None:
        manifest = self._manifest()
        plan = _plan([_execute(0, "o-1", "m1")])
        dry_state = _ExecutionState(manifest=manifest, dry_run=True, results=[])
        dry_manifest, dry_status, dry_rev = ExecutorAgent._conclude(
            manifest, dry_state, dry_run=True
        )
        assert dry_manifest is not manifest
        assert dry_status == "dry-run-completed"
        assert dry_rev == manifest.revision

        dry_failed = _ExecutionState(
            manifest=manifest, dry_run=True, results=[], failed_step_index=0
        )
        _, dry_failed_status, _ = ExecutorAgent._conclude(
            manifest, dry_failed, dry_run=True
        )
        assert dry_failed_status == "failed"

        live_working = manifest.model_copy(deep=True)
        replan_state = _ExecutionState(
            manifest=live_working,
            dry_run=False,
            results=[],
            replan_required=True,
        )
        _, replan_status, replan_rev = ExecutorAgent._conclude(
            manifest, replan_state, dry_run=False
        )
        assert replan_status == "replan-required"
        assert replan_rev == manifest.revision + 1

        failed_state = _ExecutionState(
            manifest=manifest.model_copy(deep=True),
            dry_run=False,
            results=[],
            failed_step_index=0,
        )
        _, failed_status, _ = ExecutorAgent._conclude(
            manifest, failed_state, dry_run=False
        )
        assert failed_status == "failed"

        report = ExecutorAgent._build_report(
            plan,
            manifest,
            replan_state,
            status=replan_status,
            revision_after=replan_rev,
            started_at=NOW,
            completed_at=NOW,
        )
        expected_seed = f"{plan.plan_id}:{manifest.manifest_id}:{NOW.isoformat()}:live"
        assert report.execution_id == (
            "execution-" + hashlib.sha256(expected_seed.encode()).hexdigest()[:16]
        )
        assert report.status == "replan-required"
        assert report.replan_required is True
        assert report.manifest_revision_after == replan_rev

    def test_selection_is_synced_and_discovered_open_obligations_request_a_replan(
        self,
    ) -> None:
        manifest = self._manifest()
        planned_id = manifest.obligations[0].id
        working = manifest.model_copy(deep=True)
        discovered = build_obligation(
            "describe-image", ["e1"], ["vision-description"]
        ).model_copy(update={"id": "obligation-discovered", "selected": True})
        working.obligations.append(discovered)
        plan = _plan([_execute(0, planned_id, "vision-description")]).model_copy(
            update={"selected_obligations": [planned_id]}
        )

        assert ExecutorAgent._sync_selection(plan, manifest, working) is True
        assert working.obligations[0].selected is True

        discovered.status = "satisfied"
        assert ExecutorAgent._sync_selection(plan, manifest, working) is False


class TestPddlActionSequenceCharacterization:
    def _projection(self):
        manifest = build_manifest(
            [build_element("e1", "picture", text="")],
            [build_obligation("describe-image", ["e1"], ["vision-description", "human-review"])],
        )
        compiled = PddlProblemCompiler(DomainBundle.load()).compile(manifest)
        return compiled.projection, manifest.obligations[0].id

    def test_complete_job_outside_processing_is_rejected(self) -> None:
        projection, _ = self._projection()
        with pytest.raises(ValueError, match="complete-job"):
            _validate_action_sequence(
                [PlanStep(index=0, action="complete-job")], projection
            )

    def test_execute_obligation_checks_selection_method_and_cost(self) -> None:
        projection, obligation_id = self._projection()
        start = PlanStep(index=0, action="start-job")
        complete = PlanStep(index=2, action="complete-job")

        with pytest.raises(ValueError, match="missing"):
            _validate_action_sequence(
                [start, _execute(1, "missing", "vision-description"), complete],
                projection,
            )
        with pytest.raises(ValueError, match="pandoc-table"):
            _validate_action_sequence(
                [start, _execute(1, obligation_id, "pandoc-table"), complete],
                projection,
            )
        with pytest.raises(ValueError, match=f"{obligation_id}: 1;"):
            _validate_action_sequence(
                [start, _execute(1, obligation_id, "vision-description", cost=1), complete],
                projection,
            )
        cost = projection.cost(obligation_id, "vision-description")
        valid_step = _execute(1, obligation_id, "vision-description", cost=cost)
        _validate_action_sequence(
            [start, valid_step, complete],
            projection,
        )
        with pytest.raises(ValueError, match=obligation_id):
            _validate_action_sequence(
                [
                    start,
                    valid_step,
                    valid_step.model_copy(update={"index": 2}),
                    PlanStep(index=3, action="complete-job"),
                ],
                projection,
            )
        with pytest.raises(ValueError, match="normalize-formula"):
            _validate_action_sequence(
                [
                    start,
                    valid_step.model_copy(
                        update={"obligation_kind": "normalize-formula"}
                    ),
                    complete,
                ],
                projection,
            )
        without_method = replace(
            projection,
            available_methods=frozenset({"human-review"}),
            runnable_methods=frozenset({"human-review"}),
        )
        with pytest.raises(ValueError, match="vision-description"):
            _validate_action_sequence([start, valid_step, complete], without_method)
        already_tried = replace(
            projection, tried=frozenset({(obligation_id, "vision-description")})
        )
        with pytest.raises(ValueError, match=f"{obligation_id}/vision-description"):
            _validate_action_sequence([start, valid_step, complete], already_tried)
        dependent_obligation = projection.obligations[obligation_id].model_copy(
            update={"dependencies": ["unmet-dep"]}
        )
        with_unmet_dep = replace(
            projection, obligations={obligation_id: dependent_obligation}
        )
        with pytest.raises(ValueError, match=obligation_id):
            _validate_action_sequence([start, valid_step, complete], with_unmet_dep)


class TestHandlerParameterClassificationCharacterization:
    @staticmethod
    def _classify(handler):
        parameters = list(inspect.signature(handler).parameters.values())[2:]
        return [_classify_parameter(p, {"CoreConfig": CoreConfig, "RunPorts": RunPorts}) for p in parameters]

    def test_declared_misnamed_and_unbound_parameters(self) -> None:
        def declared(manifest, obligation_id, *, config: CoreConfig, ports: RunPorts):
            pass

        def misnamed(manifest, obligation_id, *, cfg: CoreConfig):
            pass

        def positional_run_parameter(manifest, obligation_id, config: CoreConfig):
            pass

        def wrong_annotation(manifest, obligation_id, *, config: RunPorts):
            pass

        def unbound(manifest, obligation_id, *, extra):
            pass

        def three_positionals(manifest, obligation_id, extra):
            pass

        assert self._classify(declared) == [("config", None), ("ports", None)]
        assert "only as `config`" in self._classify(misnamed)[0][1]
        assert "keyword-only" in self._classify(positional_run_parameter)[0][1]
        assert "annotated `CoreConfig`" in self._classify(wrong_annotation)[0][1]
        assert "no run binds" in self._classify(unbound)[0][1]
        excess = list(inspect.signature(three_positionals).parameters.values())
        assert "requires 3 positional parameters" in _positional_problems(excess)[0]
