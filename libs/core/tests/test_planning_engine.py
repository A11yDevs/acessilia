"""The planning engine seam between the planner and the workflow coordinator (#632, PR 3)."""

from pathlib import Path

import pytest
from pddl_support import (
    build_element as _element,
    build_manifest as _manifest,
    build_obligation as _obligation,
    build_orchestrator as _orchestrator,
)

from acessilia_core.planning.engine import (
    PddlPlanningEngine,
    PlanningEngine,
    PlanningProblem,
    PlanningResult,
)
from acessilia_core.planning.models import NominalPlan
from acessilia_core.planning.planner_agent import PlannerAgent


def _text_manifest():
    manifest = _manifest(
        [_element("text", "paragraph", text="First line 5\nSecond line 10")],
        [_obligation("join-tail-blocks", ["text"], ["tailjoin", "human-review"])],
    )
    manifest.obligations[0].method_costs = {"tailjoin": 1, "human-review": 100}
    return manifest


def _shape(plan: NominalPlan) -> list[tuple[str, str | None, str | None]]:
    return [(step.action, step.obligation_id, step.method) for step in plan.steps]


class _FakeEngine:
    """A planner substitute: returns a fixed plan and records the problems."""

    def __init__(self, plan: NominalPlan) -> None:
        self.result = PlanningResult(plan=plan)
        self.problems: list[PlanningProblem] = []

    def plan(self, problem: PlanningProblem) -> PlanningResult:
        self.problems.append(problem)
        return self.result


def test_the_pddl_engine_satisfies_the_protocol():
    assert isinstance(PddlPlanningEngine(), PlanningEngine)
    assert isinstance(_FakeEngine(NominalPlan.model_construct()), PlanningEngine)


def test_planning_problem_freezes_its_inputs():
    manifest = _text_manifest()
    problem = PlanningProblem.of(
        manifest, selected_roots=iter(["a"]), unavailable_methods=["m"]
    )
    assert problem.selected_roots == ("a",)
    assert problem.unavailable_methods == ("m",)
    assert PlanningProblem.of(manifest).selected_roots is None


def test_the_coordinator_uses_an_injected_engine_without_the_planner():
    manifest = _text_manifest()
    expected = PlannerAgent().plan(manifest)[1]
    orchestrator = _orchestrator()
    fake = _FakeEngine(expected)
    orchestrator._planning_engine = fake
    orchestrator.planner = None  # the coordinator must not reach the planner

    plan, comparison = orchestrator._build_plan(
        manifest, extra_unavailable=["gated-method"], selected_roots=["text"]
    )

    assert plan is expected
    assert comparison is None
    (problem,) = fake.problems
    assert problem.manifest is manifest
    assert problem.selected_roots == ("text",)
    assert "gated-method" in problem.unavailable_methods


def test_the_default_engine_keeps_the_plans_equivalent():
    manifest = _text_manifest()
    direct = PlannerAgent().plan(manifest)[1]
    plan, comparison = _orchestrator()._build_plan(manifest)
    assert _shape(plan) == _shape(direct)
    assert plan.expected_total_cost == direct.expected_total_cost
    assert plan.planner == direct.planner
    assert comparison is None


def test_the_default_engine_follows_backend_changes_after_construction():
    orchestrator = _orchestrator()
    orchestrator.planner_backend = "both"
    engine = orchestrator.planning_engine
    assert isinstance(engine, PddlPlanningEngine)
    assert engine.backend == "both"


def test_the_pddl_engine_returns_the_compiled_problem():
    manifest = _text_manifest()
    result = PddlPlanningEngine().plan(PlanningProblem.of(manifest))
    assert result.compiled is not None
    assert result.compiled.sha256 == result.plan.problem_sha256


def test_comparing_returns_the_preferred_plan_and_the_comparison():
    manifest = _text_manifest()
    result = PddlPlanningEngine(backend="both", preferred_plan="internal").plan(
        PlanningProblem.of(manifest)
    )
    assert result.comparison is not None
    assert result.plan.planner == "internal-reference"


def test_comparing_fails_when_the_preferred_backend_failed(tmp_path: Path):
    manifest = _text_manifest()
    engine = PddlPlanningEngine(
        backend="both",
        preferred_plan="fast-downward",
        fast_downward=tmp_path / "missing-fast-downward",
    )
    with pytest.raises(RuntimeError):
        engine.plan(PlanningProblem.of(manifest))
