"""What an execution changes under the same ids (#832, second review of #837).

- An obligation kept under its id whose method no longer applies (another
  kind, targets of other types, another target set, the step's method no
  longer admissible) is stale: its step is skipped and the replan decides
  again. The splits and joins of the execution (``remap_references``) are
  composed over the planned targets first, so they alone are not a change
  (#843).
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


def _three() -> ProcessingManifest:
    """``_two`` plus a second picture, ``c``, that no obligation targets."""
    manifest = _two()
    manifest.elements.append(build_element("c", "picture", text="c"))
    manifest.pages[0].element_ids.append("c")
    manifest.summary.element_count = len(manifest.elements)
    return manifest


def test_a_split_remap_is_not_a_change() -> None:
    """A split remaps an obligation's targets to the source and its new parts
    (``handlers/structure.py``): the method reads its targets when it runs,
    so the step still runs and nothing asks for a replan."""
    from acessilia_core.pipeline.handlers.structure import (
        remap_references,
        replace_elements,
    )

    manifest = _two()
    calls: list[str] = []

    def split(m: ProcessingManifest) -> None:
        source = next(element for element in m.elements if element.id == "b")
        part = source.model_copy(update={"id": "b-2"}, deep=True)
        replace_elements(m, {"b": [source, part]})
        remap_references(m, {"b": ["b", "b-2"]})

    _, report = _executing(split, calls).execute(_plan(manifest), manifest)

    assert calls == ["o-1", "o-2"]
    assert report.status == "completed"


def test_a_join_remap_is_not_a_change() -> None:
    """A join drops an element and remaps its references to the survivor,
    which existed already: still the same work."""
    from acessilia_core.pipeline.handlers.structure import (
        remap_references,
        replace_elements,
    )

    manifest = _three()
    calls: list[str] = []

    def join(m: ProcessingManifest) -> None:
        replace_elements(m, {"b": []})
        remap_references(m, {"b": ["c"]})

    _, report = _executing(join, calls).execute(_plan(manifest), manifest)

    assert calls == ["o-1", "o-2"]
    assert report.status == "completed"


@pytest.mark.parametrize("retarget", [["c"], ["b", "c"]], ids=["swapped", "added"])
def test_a_same_type_retarget_makes_the_step_stale(retarget) -> None:
    """#843: one picture swapped for another, or a pre-existing picture added,
    keeps the types but is not the step the plan was made for: it is
    skipped and the replan decides again."""
    manifest = _three()
    calls: list[str] = []

    def retarget_o2(m: ProcessingManifest) -> None:
        _by_id(m, "o-2").target_ids = list(retarget)

    updated, report = _executing(retarget_o2, calls).execute(_plan(manifest), manifest)

    assert calls == ["o-1"]
    assert _step(report, "o-2").status == "skipped"
    assert _step(report, "o-2").message == t(EXE_OBLIGATION_CHANGED).format(obligation_id="o-2")
    assert report.status == "replan-required"
    assert "o-2" in _replannable_obligation_ids(updated)


def _stale(change, manifest: ProcessingManifest | None = None) -> bool:
    """Whether ``change``, made by ``o-1``'s handler, makes ``o-2``'s step stale."""
    manifest = manifest or _three()
    calls: list[str] = []
    _, report = _executing(change, calls).execute(_plan(manifest), manifest)
    stale = _step(report, "o-2").status == "skipped"
    assert stale == (report.status == "replan-required") and stale == ("o-2" not in calls)
    return stale


def _new_picture(m: ProcessingManifest, element_id: str) -> None:
    m.elements.append(build_element(element_id, "picture", text=element_id))
    m.pages[0].element_ids.append(element_id)
    m.summary.element_count = len(m.elements)


def test_a_new_element_added_without_a_split_is_a_change() -> None:
    """#885 review: a new id is not always a split's part. One added to the
    targets with no remap recorded is a retarget."""
    def add(m: ProcessingManifest) -> None:
        _new_picture(m, "x")
        _by_id(m, "o-2").target_ids = ["b", "x"]

    assert _stale(add)


def test_a_drop_then_a_retarget_without_a_join_is_a_change() -> None:
    """#885 review: ``b`` is removed and ``o-2`` pointed at ``c`` by hand,
    with no join mapping ``b`` to ``c``."""
    from acessilia_core.pipeline.handlers.structure import replace_elements

    def drop_and_retarget(m: ProcessingManifest) -> None:
        replace_elements(m, {"b": []})
        _by_id(m, "o-2").target_ids = ["c"]

    assert _stale(drop_and_retarget)


def test_a_join_does_not_hide_a_retarget_made_with_it() -> None:
    """#885 review: a join of ``b`` into ``c``, then ``x`` added by hand."""
    from acessilia_core.pipeline.handlers.structure import (
        remap_references,
        replace_elements,
    )

    def join_and_add(m: ProcessingManifest) -> None:
        replace_elements(m, {"b": []})
        remap_references(m, {"b": ["c"]})
        _new_picture(m, "x")
        _by_id(m, "o-2").target_ids = ["c", "x"]

    assert _stale(join_and_add)


def test_a_split_then_a_join_of_its_part_is_not_a_change() -> None:
    """#885 review: ``b`` split into ``b`` and ``b-2``, then ``b-2`` joined
    into the pre-existing ``c``: the targets become ``b`` and ``c`` through
    two recorded remaps."""
    from acessilia_core.pipeline.handlers.structure import (
        remap_references,
        replace_elements,
    )

    def split_then_join(m: ProcessingManifest) -> None:
        source = next(element for element in m.elements if element.id == "b")
        replace_elements(m, {"b": [source, source.model_copy(update={"id": "b-2"}, deep=True)]})
        remap_references(m, {"b": ["b", "b-2"]})
        replace_elements(m, {"b-2": []})
        remap_references(m, {"b-2": ["c"]})

    assert not _stale(split_then_join)


def test_an_id_freed_and_reused_within_the_execution_is_not_taken_for_a_retarget() -> None:
    """#885 review: ``b-2`` is in the plan's manifest; a step drops it, and a
    split of ``b`` gives the freed id to its new part. The recorded remaps
    say what happened, whatever the ids were before."""
    from acessilia_core.pipeline.handlers.structure import (
        remap_references,
        replace_elements,
    )

    manifest = _three()
    _new_picture(manifest, "b-2")

    def drop_then_split(m: ProcessingManifest) -> None:
        replace_elements(m, {"b-2": []})
        remap_references(m, {"b-2": []})
        source = next(element for element in m.elements if element.id == "b")
        replace_elements(m, {"b": [source, source.model_copy(update={"id": "b-2"}, deep=True)]})
        remap_references(m, {"b": ["b", "b-2"]})

    assert not _stale(drop_then_split, manifest)


@pytest.mark.parametrize(("change", "stale"), [("split", False), ("retarget", True)])
def test_a_resume_keeps_the_record_of_the_splits(change, stale) -> None:
    """The process dies right after ``o-1``'s step. The execution checkpoint
    holds the remaps recorded so far, so the resumed run still tells a split
    from a retarget."""
    from acessilia_core.execution.executor import ExecutionResume
    from acessilia_core.execution.models import ExecutionStepResult
    from acessilia_core.pipeline.handlers.structure import (
        remap_references,
        replace_elements,
    )

    manifest = _three()
    calls: list[str] = []

    def act(m: ProcessingManifest) -> None:
        if change == "split":
            source = next(element for element in m.elements if element.id == "b")
            replace_elements(m, {"b": [source, source.model_copy(update={"id": "b-2"}, deep=True)]})
            remap_references(m, {"b": ["b", "b-2"]})
        else:
            _by_id(m, "o-2").target_ids = ["c"]

    executor = _executing(act, calls)
    plan = _plan(manifest)

    class Crash(BaseException):
        """The process dies after the first step."""

    snapshots: list[dict] = []

    def save(snapshot: dict) -> None:
        snapshots.append(snapshot)
        if len(snapshot["results"]) == 1:
            raise Crash()

    with pytest.raises(Crash):
        executor.execute(plan, manifest, on_step=save)
    last = snapshots[-1]
    resume = ExecutionResume(
        manifest=ProcessingManifest.model_validate(last["manifest"]),
        results=[ExecutionStepResult.model_validate(item) for item in last["results"]],
        replan_required=bool(last["replan_required"]),
        remaps=last["remaps"],
    )

    _, report = executor.execute(plan, manifest, resume=resume)

    assert (_step(report, "o-2").status == "skipped") is stale
    assert ("o-2" in calls) is not stale


@pytest.mark.parametrize(("change", "plans", "targets"), [("split", 1, ["b", "b-2"]), ("retarget", 2, ["c"])])
def test_the_orchestrator_replans_a_retarget_and_not_a_split(monkeypatch, tmp_path, change, plans, targets) -> None:
    """The whole loop: a retarget is skipped, replanned and run on its new
    target, and the job completes; a split runs in the same plan and costs
    no replan."""
    from pddl_support import build_orchestrator

    from acessilia_core.pipeline.handlers.structure import (
        remap_references,
        replace_elements,
    )

    manifest = build_manifest(
        [build_element(name, "paragraph", text=name) for name in ("a", "b", "c")],
        [_obligation("o-1", "review-structure", ["a"]), _obligation("o-2", "review-structure", ["b"])],
    )
    orchestrator = build_orchestrator()
    seen: dict[str, list[str]] = {}

    def review(m: ProcessingManifest, obligation_id: str) -> MethodResult:
        seen[obligation_id] = list(_by_id(m, obligation_id).target_ids)
        if obligation_id == "o-1" and change == "split":
            source = next(element for element in m.elements if element.id == "b")
            replace_elements(m, {"b": [source, source.model_copy(update={"id": "b-2"}, deep=True)]})
            remap_references(m, {"b": ["b", "b-2"]})
        elif obligation_id == "o-1":
            _by_id(m, "o-2").target_ids = ["c"]
        return MethodResult(success=True, validated=True)

    orchestrator.executor.registry.register("human-review", review)
    built = []
    original = orchestrator._build_plan
    monkeypatch.setattr(orchestrator, "_build_plan", lambda *a, **k: built.append(1) or original(*a, **k))

    payload = _run(orchestrator, manifest, tmp_path, monkeypatch)

    assert len(built) == plans
    assert seen["o-2"] == targets
    assert payload["canonical_metadata"]["pddl_execution_status"] == "completed"
    assert payload["canonical_metadata"]["pddl_unsatisfied_obligations"] == []


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


def test_a_discovery_that_waits_for_the_failed_work_still_stops(monkeypatch, tmp_path) -> None:
    """A found obligation that depends on the failed one is touched by the
    failure: with the failure budget spent it is not replanned, and, being
    critical, it fails the job instead of being delivered silently."""
    calls: list[str] = []
    orchestrator, manifest = _failing_and_finding(
        calls, max_replans=0, failing_kind="repair-heading-hierarchy"
    )
    review = orchestrator.executor.registry.get("human-review")

    def finding_a_dependent(m: ProcessingManifest, obligation_id: str) -> MethodResult:
        result = review(m, obligation_id)
        for item in m.obligations:
            if item.id.startswith("o-found") and "o-bad" not in item.dependencies:
                item.dependencies.append("o-bad")
        return result

    orchestrator.executor.registry.register("human-review", finding_a_dependent)

    with pytest.raises(RuntimeError, match="review-structure"):
        _run(orchestrator, manifest, tmp_path, monkeypatch)

    assert "o-found-1" not in calls
    assert "o-bad:alternative" not in calls


# The delivery after a discovery replan, and the roots at any depth, are
# tested in test_discovery_after_failure_budget.py.


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


def test_a_stale_edge_to_an_exhausted_enrichment_does_not_block_the_replan() -> None:
    """An edge to a ``failed`` enrichment blocks its dependents from being
    replanned, so it cannot outlive the target that justified it: an
    obligation retargeted to a table with an open enrichment is replannable
    again."""
    manifest = _tables("t-1")
    moved = _obligation("o-moved", "review-structure", ["t-1"])
    moved.selected = True
    manifest.obligations.append(moved)
    manifest.summary.obligation_count = len(manifest.obligations)
    first = add_table_enrichment_obligation(manifest)
    first.status = "failed"
    _by_id(manifest, "lin-t-1").status = "failed"
    assert moved.dependencies == [first.id]
    assert "o-moved" not in _replannable_obligation_ids(manifest)

    _add_table(manifest, "t-2")
    second = add_table_enrichment_obligation(manifest, replan=True)
    moved.target_ids = ["t-2"]
    add_table_enrichment_obligation(manifest)

    assert first.id not in moved.dependencies
    assert moved.dependencies == [second.id]
    assert "o-moved" in _replannable_obligation_ids(manifest)
    _valid(manifest)
