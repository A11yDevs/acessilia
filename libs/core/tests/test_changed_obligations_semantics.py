"""What an execution changes under the same ids (#832, second review of #837).

- An obligation kept under its id whose method no longer applies (another
  kind, targets of other types, the step's method no longer admissible) is
  stale: its step is skipped and the replan decides again. A retarget that
  keeps the types (a split or a join) is not a change.
- The replan guard compares the planning state after the reconciliation, not
  only the ids of the open obligations.
- A run with a failure and a discovery is a failure replan: the discovery
  budget never bypasses the failure one, and a critical obligation left open
  fails the job.
- The table enrichment's edges follow the current targets.
"""

from __future__ import annotations

import pytest
from pddl_support import build_element, build_manifest
from test_changed_obligations import (
    _add_table,
    _discovering_orchestrator,
    _lose,
    _obligation,
    _plan,
    _run,
    _step,
    _tables,
    _valid,
)

from acessilia_core.execution.executor import ExecutorAgent, MethodRegistry
from acessilia_core.execution.messages import EXE_OBLIGATION_CHANGED
from acessilia_core.execution.models import MethodResult
from acessilia_core.i18n import t
from acessilia_core.manifest.models import ProcessingManifest
from acessilia_core.pipeline.obligations import (
    TABLE_ENRICHMENT_OBLIGATION_ID,
    _replannable_obligation_ids,
    add_table_enrichment_obligation,
    planning_signature,
)
from acessilia_core.planning.domain_bundle import DomainBundle
from acessilia_core.planning.planner_agent import PlannerAgent


def _two() -> ProcessingManifest:
    return build_manifest(
        [build_element("a", "paragraph", text="a"), build_element("b", "picture", text="b")],
        [_obligation("o-1", "review-structure", ["a"]), _obligation("o-2", "describe-image", ["b"])],
    )


def _executing(change, calls: list[str]) -> ExecutorAgent:
    def review(manifest: ProcessingManifest, obligation_id: str) -> MethodResult:
        calls.append(obligation_id)
        if obligation_id == "o-1":
            change(manifest)
        return MethodResult(success=True, validated=True)

    registry = MethodRegistry()
    registry.register("human-review", review)
    registry.register("vision-description", review)
    return ExecutorAgent(registry, domain=DomainBundle.load())


def _by_id(manifest: ProcessingManifest, obligation_id: str):
    return next(item for item in manifest.obligations if item.id == obligation_id)


# Changes under the same id.


def test_a_target_of_another_type_makes_the_step_stale() -> None:
    """The picture became a formula without a reconciliation: describing it
    would run a handler on an element it does not apply to."""
    manifest = _two()
    calls: list[str] = []

    def retype(m: ProcessingManifest) -> None:
        next(element for element in m.elements if element.id == "b").type = "formula"

    updated, report = _executing(retype, calls).execute(_plan(manifest), manifest)

    assert calls == ["o-1"]
    assert _step(report, "o-2").status == "skipped"
    assert _step(report, "o-2").message == t(EXE_OBLIGATION_CHANGED).format(obligation_id="o-2")
    assert report.failed_step_index is None
    assert report.status == "replan-required"
    assert "o-2" in _replannable_obligation_ids(updated)


def test_a_method_no_longer_admissible_makes_the_step_stale() -> None:
    """A handler narrowed the obligation's methods (as the formula stage does
    for a region it cannot tell): the planned method no longer applies, and
    the replan picks one that does instead of failing the step."""
    manifest = _two()
    calls: list[str] = []

    def narrow(m: ProcessingManifest) -> None:
        item = _by_id(m, "o-2")
        item.admissible_methods = ["vision-description"]
        item.method_costs = {"vision-description": 5}

    executor = _executing(narrow, calls)
    updated, report = executor.execute(_plan(manifest), manifest)

    assert _step(report, "o-2").status == "skipped"
    assert report.failed_step_index is None
    _, again = executor.execute(_plan(updated, _replannable_obligation_ids(updated)), updated)
    assert again.status == "completed"
    assert calls == ["o-1", "o-2"]


def test_a_retarget_that_keeps_the_types_is_not_a_change() -> None:
    """A split remaps an obligation's targets to the parts (``handlers/structure.py``):
    the method reads its targets when it runs, so the step still runs."""
    manifest = _two()
    calls: list[str] = []

    def split(m: ProcessingManifest) -> None:
        m.elements.append(build_element("b-2", "picture", text="b2"))
        m.summary.element_count = len(m.elements)
        _by_id(m, "o-2").target_ids = ["b", "b-2"]

    _, report = _executing(split, calls).execute(_plan(manifest), manifest)

    assert calls == ["o-1", "o-2"]
    assert report.status == "completed"


def test_an_enrichment_id_freed_by_a_removal_is_reused_by_the_next_plan() -> None:
    """The id policy: ids are unique in a manifest, and one freed by a removal
    may come back in a later plan. Within one execution the step compares the
    obligation with the plan's, so a reused id never runs a stale step."""
    manifest = _tables("t-1")
    add_table_enrichment_obligation(manifest)
    _lose(manifest, "t-1")
    assert add_table_enrichment_obligation(manifest) is None
    _add_table(manifest, "t-2")

    again = add_table_enrichment_obligation(manifest, replan=True)

    assert (again.id, again.target_ids, again.selected) == (TABLE_ENRICHMENT_OBLIGATION_ID, ["t-2"], True)
    _valid(manifest)
    PlannerAgent().plan(manifest, selected_roots=[again.id])


# The replan guard.


def test_the_same_ids_with_other_targets_are_another_planning_state() -> None:
    manifest = _two()
    for item in manifest.obligations:
        item.selected = True
    before = planning_signature(manifest)
    assert planning_signature(manifest) == before  # deterministic

    manifest.elements.append(build_element("c", "paragraph", text="c"))
    manifest.summary.element_count = len(manifest.elements)
    _by_id(manifest, "o-1").target_ids = ["c"]

    assert planning_signature(manifest) != before


def test_the_same_ids_with_other_dependencies_are_another_planning_state() -> None:
    manifest = _two()
    for item in manifest.obligations:
        item.selected = True
    before = planning_signature(manifest)

    _by_id(manifest, "o-2").dependencies.append("o-1")

    assert planning_signature(manifest) != before


# A failure and a discovery in the same run.


def _failing_and_finding(calls: list[str], *, max_replans: int, failing_kind: str):
    """``o-1`` finds ``o-found-1``; ``o-bad`` fails its first method and has
    an alternative."""
    orchestrator = _discovering_orchestrator(calls, max_replans=max_replans)

    def bad(_m: ProcessingManifest, obligation_id: str) -> MethodResult:
        calls.append(f"{obligation_id}:first")
        return MethodResult(success=False, validated=False, message="no")

    def alternative(_m: ProcessingManifest, obligation_id: str) -> MethodResult:
        calls.append(f"{obligation_id}:alternative")
        return MethodResult(success=True, validated=True)

    orchestrator.executor.registry.register("first-method", bad)
    orchestrator.executor.registry.register("alternative-method", alternative)
    bad_obligation = _obligation("o-bad", failing_kind, ["b"])
    bad_obligation.admissible_methods = ["first-method", "alternative-method"]
    bad_obligation.method_costs = {"first-method": 1, "alternative-method": 5}
    manifest = build_manifest(
        [build_element("a", "paragraph", text="a"), build_element("b", "heading", text="b")],
        [_obligation("o-1", "review-structure", ["a"]), bad_obligation],
    )
    return orchestrator, manifest


def test_a_failure_and_a_discovery_with_both_budgets_left_recover_both(monkeypatch, tmp_path) -> None:
    calls: list[str] = []
    orchestrator, manifest = _failing_and_finding(calls, max_replans=1, failing_kind="review-structure")

    _run(orchestrator, manifest, tmp_path, monkeypatch)

    assert "o-found-1" in calls and "o-bad:alternative" in calls


def test_a_discovery_does_not_bypass_a_spent_failure_budget(monkeypatch, tmp_path) -> None:
    """A non-critical failure next to a critical discovery, with
    ``max_replans=0``: the run is a failure replan, so it does not replan. The
    critical found obligation is open, and the job fails instead of
    delivering it silently."""
    calls: list[str] = []
    orchestrator, manifest = _failing_and_finding(
        calls, max_replans=0, failing_kind="repair-heading-hierarchy"
    )

    with pytest.raises(RuntimeError, match="review-structure"):
        _run(orchestrator, manifest, tmp_path, monkeypatch)

    assert "o-found-1" not in calls
    assert "o-bad:alternative" not in calls


# The enrichment's edges follow the targets.


def test_an_edge_whose_table_the_enrichment_lost_is_dropped() -> None:
    """Partial loss: the enrichment keeps t-1 and loses t-2, so an obligation
    about t-2 and a paragraph no longer waits for it; another dependency of
    that obligation stays."""
    manifest = _tables("t-1", "t-2")
    manifest.elements.append(build_element("p", "paragraph", text="p"))
    other = _obligation("o-other", "review-structure", ["p"])
    page = _obligation("o-page", "refine-reading-order", ["t-2", "p"])
    page.dependencies = ["o-other"]
    manifest.obligations.extend([other, page])
    manifest.summary.element_count = len(manifest.elements)
    enrichment = add_table_enrichment_obligation(manifest)
    assert page.dependencies == ["o-other", enrichment.id]

    _lose(manifest, "t-2")
    page.target_ids = ["p"]
    add_table_enrichment_obligation(manifest)

    assert enrichment.target_ids == ["t-1"]
    assert page.dependencies == ["o-other"]
    assert _by_id(manifest, "lin-t-1").dependencies == [enrichment.id]
    _valid(manifest)


def test_an_edge_of_a_retargeted_obligation_is_dropped_and_the_reconciliation_is_idempotent() -> None:
    manifest = _tables("t-1")
    manifest.elements.append(build_element("p", "paragraph", text="p"))
    moved = _obligation("o-moved", "review-structure", ["t-1"])
    manifest.obligations.append(moved)
    manifest.summary.element_count = len(manifest.elements)
    enrichment = add_table_enrichment_obligation(manifest)
    assert moved.dependencies == [enrichment.id]

    moved.target_ids = ["p"]
    add_table_enrichment_obligation(manifest)
    once = _valid(manifest).model_dump()
    add_table_enrichment_obligation(manifest)

    assert moved.dependencies == []
    assert _valid(manifest).model_dump() == once
    for item in manifest.obligations:
        item.selected = True
    PlannerAgent().plan(manifest, selected_roots=[item.id for item in manifest.obligations])


def test_an_edge_to_a_closed_enrichment_is_history_and_stays() -> None:
    manifest = _tables("t-1")
    enrichment = add_table_enrichment_obligation(manifest)
    enrichment.status = "satisfied"
    lin = _by_id(manifest, "lin-t-1")
    lin.status = "satisfied"

    add_table_enrichment_obligation(manifest)

    assert lin.dependencies == [enrichment.id]
