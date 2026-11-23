"""The seam between planning and the coordination of a workflow (#632, PR 3).

The orchestrator asks a :class:`PlanningEngine` for a plan and consumes the
:class:`PlanningResult`; it does not know which planner produced it.
:class:`PddlPlanningEngine` is the engine the pipeline uses: it wraps
:class:`~acessilia_core.planning.planner_agent.PlannerAgent` and owns the choice
of backend (the internal reference planner, Fast Downward, or both compared),
which used to live in the orchestrator. A test, or a future planning mechanism
(#619), passes its own engine to the orchestrator instead.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from acessilia_core.i18n import t
from acessilia_core.i18n.log_messages import LOG_PDDL_PREFERRED_PLAN_MISSING
from acessilia_core.manifest.models import ProcessingManifest
from acessilia_core.planning.models import NominalPlan, PlanningComparison
from acessilia_core.planning.pddl_processor import CompiledProblem
from acessilia_core.planning.planner_agent import PlannerAgent


@dataclass(frozen=True)
class PlanningProblem:
    """What a plan is asked for: the manifest and the planning restrictions.

    ``selected_roots`` limits planning to the obligations under those roots
    (``None`` plans every obligation). ``unavailable_methods`` are methods the
    plan must not use: those without a handler and those the Toolbox
    availability gate rules out.
    """

    manifest: ProcessingManifest
    selected_roots: tuple[str, ...] | None = None
    unavailable_methods: tuple[str, ...] = ()

    @classmethod
    def of(
        cls,
        manifest: ProcessingManifest,
        *,
        selected_roots: Iterable[str] | None = None,
        unavailable_methods: Iterable[str] = (),
    ) -> PlanningProblem:
        return cls(
            manifest=manifest,
            selected_roots=None if selected_roots is None else tuple(selected_roots),
            unavailable_methods=tuple(unavailable_methods),
        )


@dataclass(frozen=True)
class PlanningResult:
    """A validated plan, the problem it solves and, when compared, the comparison.

    ``compiled`` is ``None`` for an engine that does not compile PDDL (a fake in
    tests, for example).
    """

    plan: NominalPlan
    compiled: CompiledProblem | None = None
    comparison: PlanningComparison | None = None


@runtime_checkable
class PlanningEngine(Protocol):
    """Produces a plan for a problem; raises when it cannot."""

    def plan(self, problem: PlanningProblem) -> PlanningResult: ...


class PddlPlanningEngine:
    """The PDDL engine: :class:`PlannerAgent` with one backend configuration.

    ``backend`` is ``"internal"``, ``"fast-downward"`` or ``"both"``. With
    ``"both"`` the two planners solve the same compiled problem, the result
    carries their comparison, and the plan is the ``preferred_plan`` backend's;
    if that backend failed, planning fails.
    """

    def __init__(
        self,
        planner: PlannerAgent | None = None,
        *,
        backend: str = "internal",
        preferred_plan: str = "internal",
        fast_downward: Path | None = None,
        fast_downward_alias: str | None = None,
        fast_downward_search: str = "astar(blind())",
    ) -> None:
        self.planner = planner if planner is not None else PlannerAgent()
        self.backend = backend
        self.preferred_plan = preferred_plan
        self.fast_downward = fast_downward
        self.fast_downward_alias = fast_downward_alias
        self.fast_downward_search = fast_downward_search

    def plan(self, problem: PlanningProblem) -> PlanningResult:
        if self.backend == "both":
            return self._compare(problem)
        compiled, plan = self.planner.plan(
            problem.manifest,
            selected_roots=problem.selected_roots,
            unavailable_methods=problem.unavailable_methods,
            backend=self.backend,
            fast_downward=self.fast_downward,
            fast_downward_alias=self.fast_downward_alias,
            fast_downward_search=self.fast_downward_search,
        )
        return PlanningResult(plan=plan, compiled=compiled)

    def _compare(self, problem: PlanningProblem) -> PlanningResult:
        compiled, plans, comparison = self.planner.compare(
            problem.manifest,
            selected_roots=problem.selected_roots,
            unavailable_methods=problem.unavailable_methods,
            fast_downward=self.fast_downward,
            fast_downward_alias=self.fast_downward_alias,
            fast_downward_search=self.fast_downward_search,
            preferred_backend=self.preferred_plan,
        )
        if self.preferred_plan not in plans:
            raise RuntimeError(
                t(LOG_PDDL_PREFERRED_PLAN_MISSING).format(backend=self.preferred_plan)
            )
        return PlanningResult(
            plan=plans[self.preferred_plan], compiled=compiled, comparison=comparison
        )


__all__ = [
    "PddlPlanningEngine",
    "PlanningEngine",
    "PlanningProblem",
    "PlanningResult",
]
