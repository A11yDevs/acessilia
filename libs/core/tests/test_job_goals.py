"""Job goals survive partial plans and their checkpoints (#883)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from pddl_support import (
    build_element,
    build_manifest,
    build_obligation,
    build_orchestrator,
)

from acessilia_core.execution.executor import ExecutionResume
from acessilia_core.execution.models import ExecutionStepResult, MethodResult
from acessilia_core.manifest.models import ProcessingManifest
from acessilia_core.manifest.schema import validate_manifest
from acessilia_core.pipeline.obligations import (
    _reopen,
    _unsatisfied_obligations,
    replan_roots,
)
from acessilia_core.pipeline.orchestrator import PddlAccessibilityOrchestrator
from acessilia_core.pipeline.payload import build_pddl_structured_payload
from acessilia_core.planning.models import NominalPlan
from acessilia_core.planning.planner_agent import PlannerAgent


def _job():
    obligations = [
        build_obligation("repair-heading-hierarchy", ["a"], ["human-review"]).model_copy(
            update={"id": name, "selected": True}
        )
        for name in ("o-run", "o-later")
    ]
    return build_manifest([build_element("a", "heading", text="Title")], obligations)


def _executor(calls):
    executor = build_orchestrator().executor

    def review(_manifest, obligation_id):
        calls.append(obligation_id)
        return MethodResult(success=True, validated=True)

    executor.registry.register("human-review", review)
    return executor


def test_a_partial_plan_completes_while_an_open_job_goal_stays_deferred():
    manifest = _job()
    calls = []
    executor = _executor(calls)
    _, plan = PlannerAgent().plan(manifest, selected_roots=["o-run"])
    snapshots = []

    after, report = executor.execute(plan, manifest, on_step=snapshots.append)

    assert report.status == "completed"
    assert calls == ["o-run"]
    assert after.obligations[1].selected is True
    assert after.obligations[1].status != "satisfied"
    assert after.obligations[1].deferred_reason == "outside-plan"
    assert _unsatisfied_obligations(after)[0]["deferred_reason"] == "outside-plan"
    assert all(snapshot["manifest"]["obligations"][1]["selected"] for snapshot in snapshots)
    assert manifest.obligations[1].deferred_reason is None
    PddlAccessibilityOrchestrator._check_unsatisfied(after, report)
    payload = build_pddl_structured_payload(
        file_path=Path("/tmp/goals.pdf"), manifest=after, plan=plan,
        planner_backend="internal", execution_report=report, comparison=None,
    )
    assert payload["cacheable"] is False
    assert payload["technical_warnings"]


def test_a_later_plan_clears_the_deferral_and_satisfies_the_goal():
    manifest = _job()
    calls = []
    executor = _executor(calls)
    _, first = PlannerAgent().plan(manifest, selected_roots=["o-run"])
    after, _ = executor.execute(first, manifest)
    saved = after.model_dump(mode="json", by_alias=True)
    assert validate_manifest(saved) == []
    after = ProcessingManifest.model_validate(saved)
    assert after.obligations[1].deferred_reason == "outside-plan"
    _reopen(after)
    assert after.status == "processing"
    _, second = PlannerAgent().plan(after, selected_roots=["o-later"])

    finished, report = executor.execute(second, after)

    assert report.status == "completed"
    assert calls == ["o-run", "o-later"]
    assert finished.obligations[1].status == "satisfied"
    assert finished.obligations[1].deferred_reason is None
    assert _unsatisfied_obligations(finished) == []


def test_a_removed_goal_is_not_recreated_by_a_partial_plan():
    manifest = _job()
    executor = _executor([])

    def remove(working, _obligation_id):
        working.obligations = [item for item in working.obligations if item.id != "o-later"]
        working.summary.obligation_count = len(working.obligations)
        return MethodResult(success=True, validated=True)

    executor.registry.register("human-review", remove)
    _, plan = PlannerAgent().plan(manifest, selected_roots=["o-run"])

    after, report = executor.execute(plan, manifest)

    assert report.status == "completed"
    assert [item.id for item in after.obligations] == ["o-run"]
    assert _unsatisfied_obligations(after) == []


def test_a_completed_partial_plan_does_not_allow_an_open_critical_goal_to_be_delivered():
    manifest = _job()
    manifest.obligations[1].kind = "review-structure"
    _, plan = PlannerAgent().plan(manifest, selected_roots=["o-run"])
    after, report = _executor([]).execute(plan, manifest)

    assert report.status == "completed"
    with pytest.raises(RuntimeError, match="review-structure"):
        PddlAccessibilityOrchestrator._check_unsatisfied(after, report)


def test_an_unselected_obligation_outside_the_plan_does_not_become_a_job_goal():
    manifest = _job()
    manifest.obligations[1].selected = False
    _, plan = PlannerAgent().plan(manifest, selected_roots=["o-run"])

    after, report = _executor([]).execute(plan, manifest)

    assert report.status == "completed"
    assert after.obligations[1].selected is False
    assert after.obligations[1].deferred_reason is None
    assert _unsatisfied_obligations(after) == []


def test_an_old_manifest_keeps_its_plan_binding_and_round_trips_unchanged():
    legacy = _job().model_dump(mode="json", by_alias=True)
    assert all("deferred_reason" not in item for item in legacy["obligations"])
    manifest = ProcessingManifest.model_validate(legacy)
    _, plan = PlannerAgent().plan(manifest, selected_roots=["o-run"])
    old_hash = hashlib.sha256(
        json.dumps(legacy, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()

    assert plan.manifest_sha256 == old_hash
    assert manifest.model_dump(mode="json", by_alias=True) == legacy
    assert validate_manifest(legacy) == []
    _, report = _executor([]).execute(plan, manifest)
    assert report.status == "completed"


@pytest.mark.parametrize("construction", ["validated", "copied", "mutated"])
def test_a_step_outside_the_plan_scope_is_rejected_before_any_handler_runs(construction):
    manifest = _job()
    calls = []
    _, plan = PlannerAgent().plan(manifest, selected_roots=["o-run"])
    steps = [
        step.model_copy(update={"obligation_id": "o-later"}) if step.obligation_id == "o-run" else step
        for step in plan.steps
    ]
    if construction == "validated":
        with pytest.raises(ValueError):
            NominalPlan.model_validate({**plan.model_dump(), "steps": steps})
    else:
        if construction == "copied":
            plan = plan.model_copy(update={"steps": steps})
        else:
            plan.steps = steps
        with pytest.raises(ValueError):
            _executor(calls).execute(plan, manifest)
    assert calls == []


def test_a_handler_satisfying_a_deferred_goal_clears_its_reason_in_the_checkpoint():
    manifest = _job()
    executor = _executor([])

    def review(working, _obligation_id):
        working.obligations[1].status = "satisfied"
        return MethodResult(success=True, validated=True)

    executor.registry.register("human-review", review)
    _, plan = PlannerAgent().plan(manifest, selected_roots=["o-run"])
    snapshots = []

    after, report = executor.execute(plan, manifest, on_step=snapshots.append)

    assert report.status == "completed"
    assert after.obligations[1].deferred_reason is None
    assert "deferred_reason" not in snapshots[-1]["manifest"]["obligations"][1]


def test_a_dependency_discovered_during_a_partial_plan_waits_for_the_replan():
    manifest = _job()
    after_goal = manifest.obligations[0].model_copy(update={"id": "o-after"}, deep=True)
    after_goal.dependencies = ["o-run"]
    manifest.obligations.append(after_goal)
    manifest.summary.obligation_count = len(manifest.obligations)
    calls = []
    executor = _executor(calls)

    def review(working, obligation_id):
        calls.append(obligation_id)
        if obligation_id == "o-run":
            discovered = after_goal.model_copy(update={"id": "o-found", "selected": False}, deep=True)
            working.obligations.append(discovered)
            next(item for item in working.obligations if item.id == "o-after").dependencies = ["o-run", "o-found"]
            working.summary.obligation_count = len(working.obligations)
        return MethodResult(success=True, validated=True)

    executor.registry.register("human-review", review)
    _, plan = PlannerAgent().plan(manifest, selected_roots=["o-run", "o-after"])
    after, report = executor.execute(plan, manifest)
    assert calls == ["o-run"]
    assert report.status == "replan-required"
    assert after.obligations[1].selected is True
    assert after.obligations[1].deferred_reason == "outside-plan"
    roots = replan_roots(after, failure_budget_spent=False)
    _, second = PlannerAgent().plan(after, selected_roots=roots)

    finished, report = executor.execute(second, after)

    assert report.status == "completed"
    assert sorted(calls) == ["o-after", "o-found", "o-later", "o-run"]
    assert calls.index("o-found") < calls.index("o-after")
    assert _unsatisfied_obligations(finished) == []


@pytest.mark.parametrize(
    ("selected", "status", "expected"),
    [(True, "candidate", "outside-plan"), (False, "candidate", None),
     (True, "satisfied", None), (False, "failed", "outside-plan")],
)
def test_deferral_read_and_serialization_boundaries_normalize_inactive_goals(selected, status, expected):
    obligation = _job().obligations[0]
    payload = {**obligation.model_dump(), "selected": selected, "status": status, "deferred_reason": "outside-plan"}
    restored = type(obligation).model_validate(payload)
    assert restored.deferred_reason == expected
    obligation.selected, obligation.status, obligation.deferred_reason = selected, status, "outside-plan"
    assert obligation.model_dump().get("deferred_reason") == expected


def test_a_real_core_0_3_26_checkpoint_keeps_its_hash_and_recovers_a_deferred_goal():
    fixture = json.loads((Path(__file__).parent / "fixtures/job-goals-core-0.3.26.json").read_text())
    assert fixture["provenance"]["core_version"] == "0.3.26"
    manifest = ProcessingManifest.model_validate(fixture["planning_manifest"])
    plan = NominalPlan.model_validate(fixture["plan"])
    saved = fixture["execution"]
    assert saved["manifest"]["obligations"][1]["selected"] is False
    assert manifest.model_dump(mode="json", by_alias=True) == fixture["planning_manifest"]
    calls = []
    resumed, report = _executor(calls).execute(plan, manifest, resume=ExecutionResume(
        manifest=ProcessingManifest.model_validate(saved["manifest"]),
        results=[ExecutionStepResult.model_validate(item) for item in saved["results"]],
    ))
    assert report.status == "completed"
    assert calls == ["o-run"]
    assert resumed.obligations[1].selected is True
    assert _unsatisfied_obligations(resumed)[0]["id"] == "o-later"


def test_a_deferred_predecessor_in_the_plan_closure_has_its_reason_cleared():
    manifest = _job()
    manifest.obligations[0].dependencies = ["o-later"]
    manifest.obligations[1].deferred_reason = "failure-budget-exhausted"
    _, plan = PlannerAgent().plan(manifest, selected_roots=["o-run"])
    calls = []

    finished, report = _executor(calls).execute(plan, manifest)

    assert report.status == "completed"
    assert calls == ["o-later", "o-run"]
    assert all(item.deferred_reason is None for item in finished.obligations)
