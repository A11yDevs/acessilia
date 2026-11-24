"""Obligations an execution removes or replaces (#832, M0 of #640).

A reclassification during the plan (a picture the vision model reads as a
formula) removes the element's old obligations and adds new ones. The
executor already selected the added ones (#594); now it also skips, and
records, the steps of the removed ones and of those that wait for an added
one, without counting them as failures. The orchestrator replans after such a
run with its own bound, and covers new tables with their enrichment.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from core_config_support import core_config
from pddl_support import (
    build_element,
    build_manifest,
    build_obligation,
    build_orchestrator,
)

from acessilia_core.agents.model_calls import current_model_calls
from acessilia_core.execution.executor import (
    ExecutionResume,
    ExecutorAgent,
    MethodRegistry,
)
from acessilia_core.execution.messages import (
    EXE_DEPENDENCY_REMOVED,
    EXE_DISCOVERED_OBLIGATIONS_OPEN,
    EXE_OBLIGATION_REMOVED,
    EXE_OBLIGATION_WAITS_FOR_OPEN,
)
from acessilia_core.execution.models import ExecutionStepResult, MethodResult
from acessilia_core.i18n import reset_request_locale, set_request_locale, t
from acessilia_core.manifest.builder import (
    reconcile_reclassified_element_processing_needs,
)
from acessilia_core.manifest.models import Obligation, ProcessingManifest
from acessilia_core.pipeline import orchestrator as pddl, preflight
from acessilia_core.pipeline.checkpointing import PHASE_PLAN, RunCheckpoints
from acessilia_core.pipeline.obligations import (
    TABLE_ENRICHMENT_KIND,
    _replannable_obligation_ids,
    add_table_enrichment_obligation,
)
from acessilia_core.planning import toolbox_gate
from acessilia_core.planning.domain_bundle import DomainBundle
from acessilia_core.planning.planner_agent import PlannerAgent
from acessilia_core.ports import RunPorts

REPLACEMENT = "o-replacement"


def _obligation(obligation_id: str, kind: str, targets: list[str]) -> Obligation:
    item = build_obligation(kind, targets, ["human-review"])
    item.id = obligation_id
    return item


def _manifest() -> ProcessingManifest:
    elements = [build_element("a", "paragraph", text="a"), build_element("b", "picture", text="b")]
    return build_manifest(
        elements,
        [_obligation("o-1", "review-structure", ["a"]), _obligation("o-2", "describe-image", ["b"])],
    )


def _replace(manifest: ProcessingManifest, *, remove: str | None, rewire: str | None = None) -> None:
    """What a reconciliation does: remove an obligation, add its replacement,
    and make another one depend on the replacement."""
    if remove is not None:
        manifest.obligations = [item for item in manifest.obligations if item.id != remove]
    manifest.obligations.append(_obligation(REPLACEMENT, "verbalize-formula", ["b"]))
    if rewire is not None:
        next(item for item in manifest.obligations if item.id == rewire).dependencies.append(REPLACEMENT)
    manifest.summary.obligation_count = len(manifest.obligations)


def _executor(calls: list[str], change) -> ExecutorAgent:
    def review(manifest: ProcessingManifest, obligation_id: str) -> MethodResult:
        calls.append(obligation_id)
        if obligation_id == "o-1" and all(item.id != REPLACEMENT for item in manifest.obligations):
            change(manifest)
        return MethodResult(success=True, validated=True)

    registry = MethodRegistry()
    registry.register("human-review", review)
    return ExecutorAgent(registry, domain=DomainBundle.load())


def _plan(manifest: ProcessingManifest, roots: list[str] | None = None):
    _, plan = PlannerAgent().plan(manifest, selected_roots=roots or ["o-1", "o-2"])
    return plan


def _step(report, obligation_id: str):
    return next(step for step in report.steps if step.obligation_id == obligation_id)


# The executor.


def test_the_step_of_a_removed_obligation_is_skipped_not_failed() -> None:
    manifest = _manifest()
    calls: list[str] = []

    updated, report = _executor(calls, lambda m: _replace(m, remove="o-2")).execute(_plan(manifest), manifest)

    assert calls == ["o-1"]  # the removed obligation's handler never ran
    assert _step(report, "o-2").status == "skipped"
    assert _step(report, "o-2").message == t(EXE_OBLIGATION_REMOVED).format(obligation_id="o-2")
    assert report.steps[-1].action == "complete-job"
    assert report.steps[-1].status == "skipped"
    assert report.steps[-1].message == t(EXE_DISCOVERED_OBLIGATIONS_OPEN).format(
        open=f"verbalize-formula ({REPLACEMENT})"
    )
    assert report.failed_step_index is None
    assert report.status == "replan-required"
    assert _replannable_obligation_ids(updated) == [REPLACEMENT]


def test_a_step_that_now_waits_for_a_found_obligation_is_skipped() -> None:
    manifest = _manifest()
    calls: list[str] = []

    updated, report = _executor(calls, lambda m: _replace(m, remove=None, rewire="o-2")).execute(
        _plan(manifest), manifest
    )

    assert calls == ["o-1"]
    assert _step(report, "o-2").status == "skipped"
    assert _step(report, "o-2").message == t(EXE_OBLIGATION_WAITS_FOR_OPEN).format(
        obligation_id="o-2", waiting=REPLACEMENT
    )
    assert report.failed_step_index is None
    assert report.status == "replan-required"
    # The replan orders the two: the replacement, then the obligation that waits for it.
    replan = _plan(updated, _replannable_obligation_ids(updated))
    order = [step.obligation_id for step in replan.steps if step.obligation_id]
    assert order.index(REPLACEMENT) < order.index("o-2")


def test_the_replan_after_a_removal_completes() -> None:
    manifest = _manifest()
    calls: list[str] = []
    executor = _executor(calls, lambda m: _replace(m, remove="o-2"))
    updated, _ = executor.execute(_plan(manifest), manifest)

    final, report = executor.execute(_plan(updated, _replannable_obligation_ids(updated)), updated)

    assert calls == ["o-1", REPLACEMENT]
    assert report.status == "completed"
    assert all(item.status == "satisfied" for item in final.obligations)


def test_a_resumed_execution_still_skips_the_removed_obligation() -> None:
    """The skip is derived from the plan's manifest and the checkpoint's, so a
    resume after the change needs no extra state."""
    manifest = _manifest()
    plan = _plan(manifest)
    calls: list[str] = []
    executor = _executor(calls, lambda m: _replace(m, remove="o-2"))

    class Crash(BaseException):
        """A process death right after the step that changed the obligations."""

    snapshots: list[dict] = []

    def save(snapshot: dict) -> None:
        snapshots.append(snapshot)
        if len(snapshot["results"]) == 2:
            raise Crash()

    with pytest.raises(Crash):
        executor.execute(plan, manifest, on_step=save)
    resume = ExecutionResume(
        manifest=ProcessingManifest.model_validate(snapshots[-1]["manifest"]),
        results=[ExecutionStepResult.model_validate(item) for item in snapshots[-1]["results"]],
        replan_required=False,
    )

    _, report = executor.execute(plan, manifest, resume=resume)

    assert calls == ["o-1"]
    assert _step(report, "o-2").status == "skipped"
    assert report.status == "replan-required"


def test_a_failure_is_still_a_failure() -> None:
    manifest = _manifest()
    registry = MethodRegistry()
    registry.register("human-review", lambda _m, _o: MethodResult(success=False, validated=False, message="no"))

    _, report = ExecutorAgent(registry, domain=DomainBundle.load()).execute(_plan(manifest), manifest)

    assert any(step.status == "failed" for step in report.steps)
    assert report.failed_step_index is not None


def _three() -> ProcessingManifest:
    elements = [build_element(name, "paragraph", text=name) for name in ("a", "b", "c")]
    return build_manifest(
        elements,
        [_obligation(f"o-{index}", "review-structure", [name]) for index, name in enumerate("abc", 1)],
    )


def test_a_step_that_now_waits_for_a_planned_obligation_not_run_yet_is_skipped() -> None:
    """Rewired to an obligation the plan runs later: the step waits for the
    replan instead of failing its preconditions (#832)."""
    manifest = _three()
    plan = _plan(manifest, ["o-1", "o-2", "o-3"])
    order = [step.obligation_id for step in plan.steps if step.obligation_id]
    first, middle, last = order
    calls: list[str] = []

    def review(m: ProcessingManifest, obligation_id: str) -> MethodResult:
        calls.append(obligation_id)
        if obligation_id == first:
            next(item for item in m.obligations if item.id == middle).dependencies.append(last)
        return MethodResult(success=True, validated=True)

    registry = MethodRegistry()
    registry.register("human-review", review)
    executor = ExecutorAgent(registry, domain=DomainBundle.load())

    updated, report = executor.execute(plan, manifest)

    assert calls == [first, last]
    assert _step(report, middle).status == "skipped"
    assert _step(report, middle).message == t(EXE_OBLIGATION_WAITS_FOR_OPEN).format(
        obligation_id=middle, waiting=last
    )
    assert report.steps[-1].status == "skipped"  # complete-job: the deferred one is open
    assert report.failed_step_index is None
    assert report.status == "replan-required"
    final, again = executor.execute(_plan(updated, _replannable_obligation_ids(updated)), updated)
    assert again.status == "completed"
    assert calls == [first, last, middle]


def test_a_dependency_removed_without_rewiring_is_reported_as_such() -> None:
    """A removal must rewire the dependents; one left dangling is the
    handler's bug, reported by name instead of a ``KeyError``."""
    manifest = _three()
    plan = _plan(manifest, ["o-1", "o-2", "o-3"])
    first, middle, last = [step.obligation_id for step in plan.steps if step.obligation_id]

    def review(m: ProcessingManifest, obligation_id: str) -> MethodResult:
        if obligation_id == first:
            next(item for item in m.obligations if item.id == middle).dependencies.append(last)
            m.obligations = [item for item in m.obligations if item.id != last]
            m.summary.obligation_count = len(m.obligations)
        return MethodResult(success=True, validated=True)

    registry = MethodRegistry()
    registry.register("human-review", review)

    _, report = ExecutorAgent(registry, domain=DomainBundle.load()).execute(plan, manifest)

    assert _step(report, middle).status == "failed"
    assert _step(report, middle).message == "ValueError: " + t(EXE_DEPENDENCY_REMOVED).format(
        obligation_id=middle, missing=last
    )
    assert _step(report, last).status == "skipped"


def test_a_failure_with_an_alternative_is_recovered_by_the_replan() -> None:
    """Criterion 7: a failed method is a failure (it spends ``max_replans``),
    and the replan takes the obligation's other method."""
    manifest = build_manifest(
        [build_element("a", "paragraph", text="a")],
        [build_obligation("review-structure", ["a"], ["human-review", "reading-order-model"])],
    )
    manifest.obligations[0].method_costs = {"human-review": 1, "reading-order-model": 5}
    calls: list[str] = []

    def method(name: str, ok: bool):
        def run(_m: ProcessingManifest, _o: str) -> MethodResult:
            calls.append(name)
            return MethodResult(success=ok, validated=ok, message=None if ok else "no")
        return run

    registry = MethodRegistry()
    registry.register("human-review", method("human-review", False))
    registry.register("reading-order-model", method("reading-order-model", True))
    executor = ExecutorAgent(registry, domain=DomainBundle.load())

    updated, report = executor.execute(_plan(manifest, ["o-1"]), manifest)
    assert report.failed_step_index is not None and report.status == "replan-required"

    final, again = executor.execute(_plan(updated, _replannable_obligation_ids(updated)), updated)

    assert calls == ["human-review", "reading-order-model"]
    assert again.status == "completed"


def test_a_reclassification_inside_a_handler_is_followed_by_the_replan() -> None:
    """The real reconciliation, as the M1 handler will call it: a picture
    read as a formula loses ``describe-image`` and gains ``verbalize-formula``."""
    manifest = _manifest()
    calls: list[str] = []

    def review(m: ProcessingManifest, obligation_id: str) -> MethodResult:
        calls.append(obligation_id)
        if obligation_id == "o-1":
            element = next(item for item in m.elements if item.id == "b")
            element.type = "formula"
            reconcile_reclassified_element_processing_needs(m, element, previous_type="picture")
        return MethodResult(success=True, validated=True)

    def any_method(m: ProcessingManifest, obligation_id: str) -> MethodResult:
        calls.append(obligation_id)
        return MethodResult(success=True, validated=True)

    registry = MethodRegistry()
    registry.register("human-review", review)
    executor = ExecutorAgent(registry, domain=DomainBundle.load())

    updated, report = executor.execute(_plan(manifest), manifest)

    assert _step(report, "o-2").status == "skipped"
    assert report.failed_step_index is None
    roots = _replannable_obligation_ids(updated)
    found = [item for item in updated.obligations if item.id in roots]
    assert [item.kind for item in found] == ["verbalize-formula"]
    for method in found[0].admissible_methods:
        if method != "human-review":
            registry.register(method, any_method)
    _valid(updated)
    _, again = executor.execute(_plan(updated, roots), updated)
    assert again.status == "completed"


def _skip_messages(locale: str) -> tuple[str, str, str, str]:
    """The two skip messages of a removal at ``locale``, and the catalog's."""
    token = set_request_locale(locale)
    try:
        manifest = _manifest()
        _, report = _executor([], lambda m: _replace(m, remove="o-2")).execute(_plan(manifest), manifest)
        return (
            _step(report, "o-2").message,
            report.steps[-1].message,
            t(EXE_OBLIGATION_REMOVED).format(obligation_id="o-2"),
            t(EXE_DISCOVERED_OBLIGATIONS_OPEN).format(open=f"verbalize-formula ({REPLACEMENT})"),
        )
    finally:
        reset_request_locale(token)


def test_the_skip_messages_follow_the_locale() -> None:
    english = _skip_messages("en_US")
    portuguese = _skip_messages("pt_BR")

    for removed, still_open, catalog_removed, catalog_open in (english, portuguese):
        assert (removed, still_open) == (catalog_removed, catalog_open)
    assert english[:2] != portuguese[:2]  # translated, not the English fallback
    assert english[0] == "Skipped: obligation o-2 was removed or replaced during this execution"


# The orchestrator's replans.


def _run(orchestrator, manifest, tmp_path, monkeypatch):
    async def nothing(*_args, **_kwargs):
        return None

    monkeypatch.setattr(preflight, "inspect_source_media", nothing)
    for name in ("_classify_formula_regions", "_enrich_picture_descriptions", "_mark_inline_math",
                 "_enrich_formula_latex"):
        monkeypatch.setattr(pddl, name, nothing)
    orchestrator.information_structural = SimpleNamespace(process=lambda *a, **k: manifest)
    return asyncio.run(orchestrator.execute(
        tmp_path / "doc.pdf", tmp_path, structured_output=True, config=core_config(),
        model_calls=current_model_calls(), ports=RunPorts.none(),
    ))


def _discovering_orchestrator(calls: list[str], *, max_replans: int, keep_finding: bool = False):
    orchestrator = build_orchestrator(max_replans=max_replans)
    found = [0]

    def review(manifest: ProcessingManifest, obligation_id: str) -> MethodResult:
        calls.append(obligation_id)
        if obligation_id == "o-1" or keep_finding:
            found[0] += 1
            item = _obligation(f"o-found-{found[0]}", "review-structure", ["a"])
            item.selected = True
            manifest.obligations.append(item)
            manifest.summary.obligation_count = len(manifest.obligations)
        return MethodResult(success=True, validated=True)

    orchestrator.executor.registry.register("human-review", review)
    return orchestrator


def test_a_replan_for_changed_obligations_does_not_spend_the_failure_budget(monkeypatch, tmp_path) -> None:
    """With ``max_replans=0`` no failure is retried, but the obligation found
    during the run still gets its replan."""
    calls: list[str] = []
    manifest = build_manifest([build_element("a", "paragraph", text="a")], [_obligation("o-1", "review-structure", ["a"])])

    _run(_discovering_orchestrator(calls, max_replans=0), manifest, tmp_path, monkeypatch)

    assert calls == ["o-1", "o-found-1"]


def test_replans_for_changed_obligations_are_bounded(monkeypatch, tmp_path) -> None:
    """A run that keeps finding obligations stops after ``max_discovery_replans``."""
    calls: list[str] = []
    manifest = build_manifest([build_element("a", "paragraph", text="a")], [_obligation("o-1", "review-structure", ["a"])])
    orchestrator = _discovering_orchestrator(calls, max_replans=0, keep_finding=True)

    with pytest.raises(Exception):  # noqa: B017 - the job ends with work left open
        _run(orchestrator, manifest, tmp_path, monkeypatch)

    assert len(calls) == 1 + orchestrator.max_discovery_replans


def test_a_replan_that_makes_no_progress_is_not_repeated() -> None:
    orchestrator = build_orchestrator(max_replans=2)
    state = "signature-of-a-state"

    assert orchestrator._replan_allowed(False, 0, 0, state, None)
    assert not orchestrator._replan_allowed(False, 0, 1, state, state)
    assert orchestrator._replan_allowed(True, 1, 0, state, state)
    assert not orchestrator._replan_allowed(True, 2, 0, state, None)


# Document-level obligations reconciled (#832).


def _tables(*ids: str, linearize_status: str = "candidate") -> ProcessingManifest:
    obligations = []
    for table in ids:
        item = _obligation(f"lin-{table}", "linearize-table", [table])
        item.status = linearize_status
        obligations.append(item)
    return build_manifest([build_element(table, "table", text="x") for table in ids], obligations)


def _add_table(manifest: ProcessingManifest, table: str) -> None:
    manifest.elements.append(build_element(table, "table", text="y"))
    manifest.obligations.append(_obligation(f"lin-{table}", "linearize-table", [table]))
    manifest.summary.element_count = len(manifest.elements)
    manifest.summary.obligation_count = len(manifest.obligations)


def test_a_table_found_after_the_enrichment_ran_gets_its_own() -> None:
    manifest = _tables("t-1")
    first = add_table_enrichment_obligation(manifest)
    first.status = "satisfied"
    next(item for item in manifest.obligations if item.id == "lin-t-1").status = "satisfied"
    _add_table(manifest, "t-2")

    second = add_table_enrichment_obligation(manifest)

    assert second.id == "obligation-enrich-tables-2"
    assert second.target_ids == ["t-2"] and second.selected
    assert first.target_ids == ["t-1"]  # the satisfied one is not reopened
    by_id = {item.id: item for item in manifest.obligations}
    assert by_id["lin-t-2"].dependencies == [second.id]
    assert by_id["lin-t-1"].dependencies == [first.id]
    # The plan accepts the state: no satisfied obligation waits for an open one.
    PlannerAgent().plan(manifest, selected_roots=["lin-t-2"])


def test_a_table_found_before_the_enrichment_ran_joins_it() -> None:
    manifest = _tables("t-1")
    first = add_table_enrichment_obligation(manifest)
    _add_table(manifest, "t-2")

    assert add_table_enrichment_obligation(manifest) is first
    assert first.target_ids == ["t-1", "t-2"]
    assert len([item for item in manifest.obligations if item.kind == TABLE_ENRICHMENT_KIND]) == 1


def _lose(manifest: ProcessingManifest, table: str) -> None:
    """What the step that removes an element does: its own obligations and
    the page's reference go with it."""
    manifest.elements = [element for element in manifest.elements if element.id != table]
    manifest.obligations = [item for item in manifest.obligations if item.id != f"lin-{table}"]
    for page in manifest.pages:
        page.element_ids = [element_id for element_id in page.element_ids if element_id != table]
    manifest.summary.element_count = len(manifest.elements)


def _valid(manifest: ProcessingManifest) -> ProcessingManifest:
    """The round trip of a checkpoint: the manifest must still validate."""
    return ProcessingManifest.model_validate(manifest.model_dump(mode="json", by_alias=True))


def test_an_open_enrichment_drops_a_table_the_document_lost() -> None:
    manifest = _tables("t-1", "t-2")
    first = add_table_enrichment_obligation(manifest)
    _lose(manifest, "t-2")

    add_table_enrichment_obligation(manifest)

    assert first.target_ids == ["t-1"]
    _valid(manifest)


def test_a_closed_enrichment_also_drops_a_lost_table() -> None:
    """A satisfied one is pruned too: ``target_ids`` may not reference an
    element the document lost, whatever the obligation's status."""
    manifest = _tables("t-1", "t-2")
    first = add_table_enrichment_obligation(manifest)
    first.status = "satisfied"
    for obligation in manifest.obligations:
        if obligation.kind == "linearize-table":
            obligation.status = "satisfied"
    _lose(manifest, "t-2")

    add_table_enrichment_obligation(manifest)

    assert first.target_ids == ["t-1"]
    _valid(manifest)


def test_a_closed_enrichment_that_lost_every_table_is_removed() -> None:
    manifest = _tables("t-1")
    first = add_table_enrichment_obligation(manifest)
    first.status = "satisfied"
    next(item for item in manifest.obligations if item.id == "lin-t-1").status = "satisfied"
    manifest.elements.append(build_element("a", "paragraph", text="a"))
    other = _obligation("o-other", "review-structure", ["a"])
    other.dependencies = [first.id]
    manifest.obligations.append(other)
    manifest.summary.element_count = len(manifest.elements)
    manifest.summary.obligation_count = len(manifest.obligations)
    _lose(manifest, "t-1")

    assert add_table_enrichment_obligation(manifest) is None

    assert all(item.kind != TABLE_ENRICHMENT_KIND for item in manifest.obligations)
    assert other.dependencies == []
    _valid(manifest)


def test_an_open_enrichment_that_lost_every_table_is_removed() -> None:
    """An empty ``target_ids`` would break the checkpoint and fail the job on
    a critical obligation with nothing to read."""
    manifest = _tables("t-1")
    add_table_enrichment_obligation(manifest)
    other = _obligation("o-other", "review-structure", ["t-1"])
    _lose(manifest, "t-1")
    manifest.elements.append(build_element("a", "paragraph", text="a"))
    other.target_ids = ["a"]
    other.dependencies = ["obligation-enrich-tables"]
    manifest.obligations.append(other)
    manifest.summary.element_count = len(manifest.elements)

    assert add_table_enrichment_obligation(manifest) is None

    assert all(item.kind != TABLE_ENRICHMENT_KIND for item in manifest.obligations)
    assert other.dependencies == []
    restored = _valid(manifest)
    assert restored.summary.obligation_count == len(restored.obligations)


def test_an_exhausted_enrichment_takes_no_new_table() -> None:
    """A ``failed`` enrichment is not planned again, so a table that joined
    it would never be read and its obligations could never be planned."""
    manifest = _tables("t-1")
    first = add_table_enrichment_obligation(manifest)
    first.status = "failed"
    lin_t1 = next(item for item in manifest.obligations if item.id == "lin-t-1")
    lin_t1.status = "failed"
    _add_table(manifest, "t-2")
    next(item for item in manifest.obligations if item.id == "lin-t-2").selected = True

    second = add_table_enrichment_obligation(manifest, replan=True)

    assert first.target_ids == ["t-1"]
    assert second.id == "obligation-enrich-tables-2" and second.target_ids == ["t-2"]
    lin_t2 = next(item for item in manifest.obligations if item.id == "lin-t-2")
    assert lin_t2.dependencies == [second.id]
    assert lin_t1.dependencies == [first.id]  # a closed obligation is left as it is
    assert {second.id, "lin-t-2"} <= set(_replannable_obligation_ids(manifest))


def test_every_open_obligation_about_a_table_waits_for_its_enrichment() -> None:
    """A rule, not a list of kinds: an obligation of any kind with a table
    among its targets comes after the table is read, as before planning."""
    manifest = _tables("t-1")
    page = _obligation("o-page", "adjudicate-page", ["t-1"])
    done = _obligation("o-done", "guard-repetition", ["t-1"])
    done.status = "satisfied"
    manifest.obligations.extend([page, done])
    manifest.summary.obligation_count = len(manifest.obligations)

    enrichment = add_table_enrichment_obligation(manifest)

    assert page.dependencies == [enrichment.id]
    assert done.dependencies == []  # a satisfied obligation is left as it is


# The orchestrator: the table call site, the bound, the checkpoint.


def test_a_table_found_during_the_run_is_enriched_before_its_obligations(monkeypatch, tmp_path) -> None:
    """The call before each replan (#832): the replan reads the new table
    before it linearizes it."""
    calls: list[str] = []
    manifest = build_manifest([build_element("a", "paragraph", text="a")], [_obligation("o-1", "review-structure", ["a"])])
    orchestrator = build_orchestrator(max_replans=0)

    def review(m: ProcessingManifest, obligation_id: str) -> MethodResult:
        calls.append(obligation_id)
        if obligation_id == "o-1":
            _add_table(m, "t-9")
            next(item for item in m.obligations if item.id == "lin-t-9").selected = True
        return MethodResult(success=True, validated=True)

    def enrich(_m: ProcessingManifest, obligation_id: str) -> MethodResult:
        calls.append(obligation_id)
        return MethodResult(success=True, validated=True)

    orchestrator.executor.registry.register("human-review", review)
    orchestrator.executor.registry.register("table-enrichment", enrich)

    _run(orchestrator, manifest, tmp_path, monkeypatch)

    assert calls == ["o-1", "obligation-enrich-tables", "lin-t-9"]


def test_the_discovery_bound_is_a_clamped_option_of_the_identity() -> None:
    from acessilia_core.pipeline.orchestrator import (
        DEFAULT_MAX_DISCOVERY_REPLANS,
        PddlAccessibilityOrchestrator,
    )

    def options(value: int) -> dict:
        orchestrator = build_orchestrator()
        orchestrator.max_discovery_replans = value
        orchestrator.max_replans = 0
        return orchestrator._checkpoint_options()["planning"]

    assert "max_discovery_replans" not in options(DEFAULT_MAX_DISCOVERY_REPLANS)
    assert options(5)["max_discovery_replans"] == 5
    assert PddlAccessibilityOrchestrator.__init__.__kwdefaults__["max_discovery_replans"] == DEFAULT_MAX_DISCOVERY_REPLANS
    clamped = PddlAccessibilityOrchestrator.__new__(PddlAccessibilityOrchestrator)
    PddlAccessibilityOrchestrator.__init__(clamped, max_discovery_replans=-1)
    assert clamped.max_discovery_replans == 0


class _Store:
    job_id = "job"
    options: dict = {}

    def __init__(self) -> None:
        self.payloads: dict[str, dict] = {}

    def load(self, phase: str):
        return self.payloads.get(phase)

    def save(self, phase: str, payload: dict) -> None:
        self.payloads[phase] = payload

    def remove(self, phase: str) -> None:
        self.payloads.pop(phase, None)


def test_the_discovery_count_survives_a_resume() -> None:
    manifest = _manifest()
    config = core_config()
    checkpoints = RunCheckpoints(_Store(), config)
    availability = toolbox_gate.AvailabilityDecision.from_metadata({}, config.toolbox)
    asyncio.run(checkpoints.save_plan(
        _plan(manifest), None, manifest, availability, [], 1, discoveries=2, previous_signature="abc",
    ))
    assert checkpoints.load(PHASE_PLAN)["discoveries"] == 2

    ctx = SimpleNamespace(checkpoints=checkpoints, config=config, status_callback=None)
    state = asyncio.run(build_orchestrator()._load_or_build_plan(ctx, manifest))

    assert (state.replans, state.discoveries, state.previous_signature) == (1, 2, "abc")


def test_a_plan_checkpoint_of_0_3_12_resumes_without_a_signature() -> None:
    """Backward compatible: a checkpoint written before the guard was saved
    has neither ``discoveries`` nor ``previous_signature``."""
    manifest = _manifest()
    config = core_config()
    store = _Store()
    checkpoints = RunCheckpoints(store, config)
    availability = toolbox_gate.AvailabilityDecision.from_metadata({}, config.toolbox)
    asyncio.run(checkpoints.save_plan(_plan(manifest), None, manifest, availability, [], 1))
    for payload in store.payloads.values():
        payload.pop("discoveries", None)
        payload.pop("previous_signature", None)

    ctx = SimpleNamespace(checkpoints=checkpoints, config=config, status_callback=None)
    state = asyncio.run(build_orchestrator()._load_or_build_plan(ctx, manifest))

    assert (state.replans, state.discoveries, state.previous_signature) == (1, 0, None)
