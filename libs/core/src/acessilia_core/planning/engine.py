"""The seam between planning and the coordination of a workflow (#632, PR 3).

The orchestrator asks a :class:`PlanningEngine` for a plan and consumes the
:class:`PlanningResult`; its coordination path does not know which planner
produced it. :class:`PddlPlanningEngine` is the engine the pipeline uses by
default: it wraps :class:`~acessilia_core.planning.planner_agent.PlannerAgent`
and owns the choice of backend (the internal reference planner, Fast Downward,
or both compared), which used to live in the orchestrator. A test, or a future
planning mechanism (#619), passes its own engine to the orchestrator instead.

Value semantics (#751): :class:`PlanningProblem` and :class:`PlanningResult`
are frozen, so their fields cannot be rebound, but they hold Pydantic models
(the manifest, the plan, the comparison) by reference. The immutability is
shallow and neither is hashable. A problem is meant to be solved in the call
that builds it; one that outlives the call (a cached problem, an asynchronous
engine) sees later changes to its manifest.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from acessilia_core.i18n import t
from acessilia_core.i18n.log_messages import LOG_PDDL_PROBLEM_HASH_MISMATCH
from acessilia_core.manifest.models import ProcessingManifest
from acessilia_core.planning.models import (
    DEFAULT_FAST_DOWNWARD_SEARCH,
    DEFAULT_PLANNER_BACKEND,
    NominalPlan,
    PlannerBackend,
    PlannerSelection,
    PlanningComparison,
)
from acessilia_core.planning.pddl_processor import CompiledProblem
from acessilia_core.planning.planner_agent import PlannerAgent


@dataclass(frozen=True)
class PlanningProblem:
    """What a plan is asked for: the manifest and the planning restrictions.

    ``selected_roots`` limits planning to the obligations under those roots
    (``None`` plans every obligation). ``unavailable_methods`` are methods the
    plan must not use: those without a handler and those the Toolbox
    availability gate rules out.

    The restrictions are copied into tuples; ``manifest`` is shared, not
    copied (see the module docstring).
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

    ``compiled`` is the PDDL problem the plan solves; the coordinator checks
    that ``plan.problem_sha256`` matches it, so an engine cannot return a plan
    for another problem. It is ``None`` for an engine that does not compile
    PDDL (a fake in tests, for example), which skips the check.
    """

    plan: NominalPlan
    compiled: CompiledProblem | None = None
    comparison: PlanningComparison | None = None

    def verified(self) -> PlanningResult:
        """This result, after checking that the plan solves ``compiled``."""
        if self.compiled is not None and self.compiled.sha256 != self.plan.problem_sha256:
            raise RuntimeError(t(LOG_PDDL_PROBLEM_HASH_MISMATCH))
        return self


@runtime_checkable
class PlanningEngine(Protocol):
    """Produces a plan for a problem.

    The contract an engine keeps with the coordinator:

    - ``plan`` is synchronous. The coordinator calls it in a worker thread
      (``run_blocking``); an asynchronous engine (an LLM planner, #619) needs
      an adapter or an asynchronous variant of this protocol.
    - It is stateless between calls: the same problem gets an equivalent plan
      whatever was planned before. The coordinator may reuse one engine for
      the first plan and every replan of a run, or build one per call, so an
      engine must not rely on either. A cache is allowed only if it keeps that
      property.
    - It plans and validates; it runs no document computation, persists
      nothing and calls no provider (ADR-0029).
    """

    @property
    def identity(self) -> str:
        """A stable name for the engine and the configuration that changes its plans.

        The run reports it as ``mode: pddl-<identity>``, and an injected
        engine's identity is part of the planning checkpoint's identity, so a
        job resumed with another engine plans again.
        """

    def plan(self, problem: PlanningProblem) -> PlanningResult:
        """The validated plan for ``problem``; raises when there is none."""


def require_engine(engine: object) -> PlanningEngine:
    """``engine``, or :class:`TypeError` if it does not implement the protocol.

    Lets a coordinator reject an engine when it is injected, rather than in
    the worker thread of the first planning call.
    """
    if not isinstance(engine, PlanningEngine):
        raise TypeError(
            f"planning_engine must implement PlanningEngine, got {type(engine).__name__}"
        )
    return engine


class PddlPlanningEngine:
    """The PDDL engine: :class:`PlannerAgent` with one backend configuration.

    ``backend`` is ``"internal"``, ``"fast-downward"`` or ``"both"``. With
    ``"both"`` the two planners solve the same compiled problem, the result
    carries their comparison, and the plan is the ``preferred_plan`` backend's;
    if that backend failed, planning fails. The :class:`PlannerAgent`, which
    loads the PDDL domain, is built on the first plan unless one is given.
    """

    def __init__(
        self,
        planner: PlannerAgent | None = None,
        *,
        backend: PlannerSelection = DEFAULT_PLANNER_BACKEND,
        preferred_plan: PlannerBackend = DEFAULT_PLANNER_BACKEND,
        fast_downward: Path | None = None,
        fast_downward_alias: str | None = None,
        fast_downward_search: str = DEFAULT_FAST_DOWNWARD_SEARCH,
    ) -> None:
        self._planner = planner
        self.backend = backend
        self.preferred_plan = preferred_plan
        self.fast_downward = fast_downward
        self.fast_downward_alias = fast_downward_alias
        self.fast_downward_search = fast_downward_search

    @property
    def planner(self) -> PlannerAgent:
        if self._planner is None:
            self._planner = PlannerAgent()
        return self._planner

    @property
    def identity(self) -> str:
        """The backend, as the run has always reported it (``pddl-internal``…)."""
        return self.backend

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
        return PlanningResult(
            plan=PlannerAgent.preferred(plans, self.preferred_plan),
            compiled=compiled,
            comparison=comparison,
        )


__all__ = [
    "PddlPlanningEngine",
    "PlanningEngine",
    "PlanningProblem",
    "PlanningResult",
    "require_engine",
]
