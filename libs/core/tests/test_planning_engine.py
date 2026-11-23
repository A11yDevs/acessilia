"""The planning engine seam between the planner and the workflow coordinator (#632, PR 3)."""

from dataclasses import FrozenInstanceError, replace
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


class _FakeEngine:
    """A planner substitute: returns a fixed plan and records the problems."""

    identity = "fake"

    def __init__(self, plan: NominalPlan) -> None:
        self.result = PlanningResult(plan=plan)
        self.problems: list[PlanningProblem] = []

    def plan(self, problem: PlanningProblem) -> PlanningResult:
        self.problems.append(problem)
        return self.result


class _FailingEngine:
    identity = "failing"

    def plan(self, problem: PlanningProblem) -> PlanningResult:
        raise RuntimeError("no plan")


def test_the_pddl_engine_satisfies_the_protocol():
    assert isinstance(PddlPlanningEngine(), PlanningEngine)
    assert isinstance(_FakeEngine(NominalPlan.model_construct()), PlanningEngine)
    assert not isinstance(object(), PlanningEngine)


def test_the_pddl_engine_identity_is_its_backend():
    assert PddlPlanningEngine().identity == "internal"
    assert PddlPlanningEngine(backend="both").identity == "both"


def test_the_pddl_engine_builds_its_planner_on_first_use():
    engine = PddlPlanningEngine()
    assert engine._planner is None
    assert isinstance(engine.planner, PlannerAgent)
    assert engine.planner is engine.planner


def test_planning_problem_materializes_its_inputs():
    manifest = _text_manifest()
    problem = PlanningProblem.of(
        manifest, selected_roots=iter(["a"]), unavailable_methods=["m"]
    )
    assert problem.selected_roots == ("a",)
    assert problem.unavailable_methods == ("m",)
    assert PlanningProblem.of(manifest).selected_roots is None


def test_planning_problem_is_frozen_but_shares_its_manifest():
    """Shallow immutability (#751): fields cannot be rebound, but the manifest
    is shared, so a later change to it is visible through the problem."""
    manifest = _text_manifest()
    problem = PlanningProblem.of(manifest)
    with pytest.raises(FrozenInstanceError):
        problem.manifest = _text_manifest()  # type: ignore[misc]
    manifest.obligations[0].method_costs["tailjoin"] = 7
    assert problem.manifest.obligations[0].method_costs["tailjoin"] == 7


def test_the_coordinator_uses_an_injected_engine_without_the_planner(monkeypatch):
    from acessilia_core.pipeline import orchestrator as orchestrator_module

    manifest = _text_manifest()
    expected = PlannerAgent().plan(manifest)[1]
    orchestrator = _orchestrator()
    fake = _FakeEngine(expected)
    orchestrator.planning_engine = fake
    orchestrator.planner = None

    def no_planner():
        raise AssertionError("the coordinator built a PlannerAgent")

    monkeypatch.setattr(orchestrator_module, "PlannerAgent", no_planner)

    plan, comparison = orchestrator._build_plan(
        manifest, extra_unavailable=["gated-method"], selected_roots=["text"]
    )

    assert plan is expected
    assert comparison is None
    (problem,) = fake.problems
    assert problem.manifest is manifest
    assert problem.selected_roots == ("text",)
    assert "gated-method" in problem.unavailable_methods


def test_an_injected_engine_is_reused_for_every_plan():
    manifest = _text_manifest()
    orchestrator = _orchestrator()
    fake = _FakeEngine(PlannerAgent().plan(manifest)[1])
    orchestrator.planning_engine = fake

    assert orchestrator.planning_engine is fake
    orchestrator._build_plan(manifest)
    orchestrator._build_plan(manifest, selected_roots=["text"])

    assert [problem.selected_roots for problem in fake.problems] == [None, ("text",)]


def test_injecting_an_object_without_the_protocol_fails_at_once():
    orchestrator = _orchestrator()
    with pytest.raises(TypeError, match="PlanningEngine"):
        orchestrator.planning_engine = object()  # type: ignore[assignment]


def test_injecting_none_restores_the_default_engine():
    orchestrator = _orchestrator()
    orchestrator.planning_engine = _FakeEngine(NominalPlan.model_construct())
    orchestrator.planning_engine = None
    assert isinstance(orchestrator.planning_engine, PddlPlanningEngine)


def test_an_engine_failure_reaches_the_coordinator():
    orchestrator = _orchestrator()
    orchestrator.planning_engine = _FailingEngine()
    with pytest.raises(RuntimeError, match="no plan"):
        orchestrator._build_plan(_text_manifest())


def test_the_coordinator_rejects_a_plan_for_another_problem():
    manifest = _text_manifest()
    compiled, plan = PlannerAgent().plan(manifest)
    other = _FakeEngine(plan)
    other.result = PlanningResult(
        plan=plan, compiled=replace(compiled, sha256="0" * 64)
    )
    orchestrator = _orchestrator()
    orchestrator.planning_engine = other
    with pytest.raises(RuntimeError, match="problem.pddl hash"):
        orchestrator._build_plan(manifest)


def test_only_an_injected_engine_enters_the_checkpoint_identity():
    orchestrator = _orchestrator()
    default = orchestrator._checkpoint_options()
    assert "planning_engine" not in default["planning"]

    orchestrator.planning_engine = _FakeEngine(NominalPlan.model_construct())
    injected = orchestrator._checkpoint_options()

    assert injected["planning"] == {**default["planning"], "planning_engine": "fake"}
    assert injected["execution"]["planning_engine"] == "fake"


def test_the_default_engine_keeps_the_plans_equivalent():
    manifest = _text_manifest()
    direct = PlannerAgent().plan(manifest)[1]
    plan, comparison = _orchestrator()._build_plan(manifest)
    # Everything but the generation time, which differs between two calls.
    assert plan.model_dump(exclude={"generated_at"}) == direct.model_dump(
        exclude={"generated_at"}
    )
    assert comparison is None


def test_the_default_engine_follows_backend_changes_after_construction():
    orchestrator = _orchestrator()
    orchestrator.planner_backend = "both"
    engine = orchestrator.planning_engine
    assert isinstance(engine, PddlPlanningEngine)
    assert engine.backend == "both"
    assert engine.planner is orchestrator.planner


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
    with pytest.raises(RuntimeError, match="fast-downward"):
        engine.plan(PlanningProblem.of(manifest))
