from __future__ import annotations

from importlib.util import find_spec

import pytest

from backend.core.execution.executor import ExecutorAgent, MethodRegistry
from backend.core.execution.models import MethodResult
from backend.core.planning.planner_agent import PlannerAgent
from tests.test_pddl_planning import make_manifest


@pytest.mark.skipif(find_spec("agno") is None, reason="Agno não instalado")
def test_executor_runs_nominal_plan_as_agno_workflow_dry_run():
    manifest = make_manifest()
    _, plan = PlannerAgent().plan(
        manifest,
        selected_roots=["o-describe"],
    )

    resulting_manifest, report = ExecutorAgent().execute(
        plan,
        manifest,
        dry_run=True,
    )

    assert report.status == "dry-run-completed"
    assert [step.status for step in report.steps] == [
        "simulated",
        "simulated",
        "simulated",
        "simulated",
    ]
    assert resulting_manifest == manifest


@pytest.mark.skipif(find_spec("agno") is None, reason="Agno não instalado")
def test_failed_method_is_recorded_and_replanning_uses_alternative():
    manifest = make_manifest()
    _, plan = PlannerAgent().plan(
        manifest,
        selected_roots=["o-describe"],
    )
    registry = MethodRegistry()
    registry.register(
        "docling",
        lambda _manifest, _obligation: MethodResult(
            success=True,
            validated=True,
        ),
    )
    registry.register(
        "vision",
        lambda _manifest, _obligation: MethodResult(
            success=False,
            validated=False,
            message="falha controlada",
        ),
    )

    updated, report = ExecutorAgent(registry).execute(plan, manifest)

    assert report.status == "replan-required"
    described = next(
        item for item in updated.obligations if item.id == "o-describe"
    )
    assert described.status == "pending"
    assert described.attempts[0].method == "vision"

    _, replanned = PlannerAgent().plan(
        updated,
        selected_roots=["o-describe"],
    )
    methods = [
        step.method
        for step in replanned.steps
        if step.obligation_id == "o-describe"
    ]
    assert methods == ["human-review"]


@pytest.mark.skipif(find_spec("agno") is None, reason="Agno não instalado")
def test_handler_exception_is_recorded_as_failed_attempt_and_replan_is_requested():
    manifest = make_manifest()
    _, plan = PlannerAgent().plan(
        manifest,
        selected_roots=["o-describe"],
    )
    registry = MethodRegistry()
    registry.register(
        "docling",
        lambda _manifest, _obligation: MethodResult(
            success=True,
            validated=True,
        ),
    )

    def failing_handler(_manifest, _obligation):
        raise RuntimeError("falha inesperada")

    registry.register("vision", failing_handler)

    updated, report = ExecutorAgent(registry).execute(plan, manifest)

    assert report.status == "replan-required"
    described = next(
        item for item in updated.obligations if item.id == "o-describe"
    )
    assert described.status == "pending"
    assert len(described.attempts) == 1
    assert described.attempts[0].method == "vision"
    assert described.attempts[0].status == "failed"
    assert described.attempts[0].message == "RuntimeError: falha inesperada"
