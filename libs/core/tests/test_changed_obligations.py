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
    EXE_DISCOVERED_OBLIGATIONS_OPEN,
    EXE_OBLIGATION_REMOVED,
    EXE_OBLIGATION_WAITS_FOR_DISCOVERED,
)
from acessilia_core.execution.models import ExecutionStepResult, MethodResult
from acessilia_core.i18n import t
from acessilia_core.manifest.models import Obligation, ProcessingManifest
from acessilia_core.pipeline import orchestrator as pddl, preflight
from acessilia_core.pipeline.obligations import (
    TABLE_ENRICHMENT_KIND,
    _replannable_obligation_ids,
    add_table_enrichment_obligation,
)
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
    assert report.steps[-1].message == t(EXE_DISCOVERED_OBLIGATIONS_OPEN).format(open=[REPLACEMENT])
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
    assert _step(report, "o-2").message == t(EXE_OBLIGATION_WAITS_FOR_DISCOVERED).format(
        obligation_id="o-2", waiting=[REPLACEMENT]
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
    open_now = frozenset({"o-x"})

    assert orchestrator._replan_allowed(False, 0, 0, open_now, None)
    assert not orchestrator._replan_allowed(False, 0, 1, open_now, open_now)
    assert orchestrator._replan_allowed(True, 1, 0, open_now, open_now)
    assert not orchestrator._replan_allowed(True, 2, 0, open_now, None)


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


def test_an_open_enrichment_drops_a_table_the_document_lost() -> None:
    manifest = _tables("t-1", "t-2")
    first = add_table_enrichment_obligation(manifest)
    manifest.elements = [element for element in manifest.elements if element.id != "t-2"]

    add_table_enrichment_obligation(manifest)

    assert first.target_ids == ["t-1"]


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
