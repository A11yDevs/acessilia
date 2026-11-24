"""Obligations a successful handler adds are selected and planned (#594).

A handler that adds content (``rescue-omitted``) derives its processing needs
while the plan runs. The executor selects them, so ``complete-job`` waits for
them and the replan takes them as roots, and a checkpoint resume keeps them.
"""

from __future__ import annotations

import pytest
from pddl_support import build_element, build_manifest, build_obligation

from acessilia_core.execution.executor import (
    ExecutionResume,
    ExecutorAgent,
    MethodRegistry,
)
from acessilia_core.execution.models import ExecutionStepResult, MethodResult
from acessilia_core.manifest.models import Obligation, ProcessingManifest
from acessilia_core.pipeline.obligations import _replannable_obligation_ids
from acessilia_core.planning.domain_bundle import DomainBundle
from acessilia_core.planning.planner_agent import PlannerAgent

DISCOVERED = "o-discovered"


def _manifest() -> ProcessingManifest:
    elements = [build_element("h", "heading", text="Title")]
    first = build_obligation("describe-image", ["h"], ["human-review"])
    first.id = "o-1"
    second = build_obligation("describe-image", ["h"], ["human-review"])
    second.id = "o-2"
    return build_manifest(elements, [first, second])


def _discovered() -> Obligation:
    return Obligation(
        id=DISCOVERED,
        kind="normalize-text",
        target_ids=["h"],
        admissible_methods=["norm-fix", "human-review"],
        method_costs={"norm-fix": 5, "human-review": 100},
        rationale="found while the plan ran",
    )


def _add(manifest: ProcessingManifest, obligation: Obligation) -> None:
    """Add an obligation as a handler does (``_append_processing_needs``)."""
    manifest.obligations.append(obligation)
    manifest.summary.obligation_count = len(manifest.obligations)


def _executor(calls: list[str], *, discover_on: str = "o-1") -> ExecutorAgent:
    def review(manifest: ProcessingManifest, obligation_id: str) -> MethodResult:
        calls.append(obligation_id)
        if obligation_id == discover_on and all(
            item.id != DISCOVERED for item in manifest.obligations
        ):
            _add(manifest, _discovered())
        return MethodResult(success=True, validated=True)

    def norm_fix(_manifest, obligation_id: str) -> MethodResult:
        calls.append(obligation_id)
        return MethodResult(success=True, validated=True)

    registry = MethodRegistry()
    registry.register("human-review", review)
    registry.register("norm-fix", norm_fix)
    return ExecutorAgent(registry, domain=DomainBundle.load())


def _plan(manifest: ProcessingManifest, roots: list[str]):
    _, plan = PlannerAgent().plan(manifest, selected_roots=roots)
    return plan


def test_a_discovered_obligation_is_selected_and_asks_for_a_replan():
    manifest = _manifest()
    calls: list[str] = []

    updated, report = _executor(calls).execute(_plan(manifest, ["o-1", "o-2"]), manifest)

    # The rest of the old plan still ran.
    assert calls == ["o-1", "o-2"]
    discovered = next(item for item in updated.obligations if item.id == DISCOVERED)
    assert discovered.selected
    assert report.status == "replan-required"
    # complete-job waited for it.
    assert report.steps[-1].action == "complete-job"
    assert report.steps[-1].status == "failed"
    assert DISCOVERED in report.steps[-1].message
    assert _replannable_obligation_ids(updated) == [DISCOVERED]


def test_the_replan_runs_the_discovered_obligation():
    manifest = _manifest()
    calls: list[str] = []
    executor = _executor(calls)
    updated, _ = executor.execute(_plan(manifest, ["o-1", "o-2"]), manifest)

    final, report = executor.execute(
        _plan(updated, _replannable_obligation_ids(updated)), updated
    )

    assert calls == ["o-1", "o-2", DISCOVERED]
    assert report.status == "completed"
    assert all(item.status == "satisfied" for item in final.obligations)
    # The attempts of the first execution are kept.
    first = next(item for item in final.obligations if item.id == "o-1")
    assert [attempt.method for attempt in first.attempts] == ["human-review"]


def test_an_obligation_added_already_satisfied_needs_no_replan():
    manifest = _manifest()

    def review(manifest: ProcessingManifest, obligation_id: str) -> MethodResult:
        if obligation_id == "o-1":
            done = _discovered()
            done.status = "satisfied"
            _add(manifest, done)
        return MethodResult(success=True, validated=True)

    registry = MethodRegistry()
    registry.register("human-review", review)
    _, report = ExecutorAgent(registry, domain=DomainBundle.load()).execute(
        _plan(manifest, ["o-1", "o-2"]), manifest
    )

    assert report.status == "completed"


def test_a_failed_handler_selects_nothing_it_added():
    manifest = _manifest()

    def review(manifest: ProcessingManifest, obligation_id: str) -> MethodResult:
        _add(manifest, _discovered())
        return MethodResult(success=False, validated=False, message="failed")

    registry = MethodRegistry()
    registry.register("human-review", review)
    updated, _ = ExecutorAgent(registry, domain=DomainBundle.load()).execute(
        _plan(manifest, ["o-1"]), manifest
    )

    assert not next(item for item in updated.obligations if item.id == DISCOVERED).selected


def test_a_resumed_execution_keeps_the_discovered_obligation():
    manifest = _manifest()
    plan = _plan(manifest, ["o-1", "o-2"])
    calls: list[str] = []
    executor = _executor(calls)

    class Crash(BaseException):
        """A process death right after the step that found the obligation."""

    snapshots: list[dict] = []

    def save(snapshot: dict) -> None:
        snapshots.append(snapshot)
        if len(snapshot["results"]) == 2:
            raise Crash()

    with pytest.raises(Crash):
        executor.execute(plan, manifest, on_step=save)
    last = snapshots[-1]
    resume = ExecutionResume(
        manifest=ProcessingManifest.model_validate(last["manifest"]),
        results=[ExecutionStepResult.model_validate(item) for item in last["results"]],
        # Even a checkpoint written without the flag asks for the replan.
        replan_required=False,
    )

    updated, report = executor.execute(plan, manifest, resume=resume)

    assert calls == ["o-1", "o-2"]
    assert next(item for item in updated.obligations if item.id == DISCOVERED).selected
    assert report.status == "replan-required"
    assert _replannable_obligation_ids(updated) == [DISCOVERED]


def test_a_resumed_execution_keeps_unselected_what_a_failed_handler_added():
    """Review of #597: resuming must not turn a failed handler's work live."""
    manifest = _manifest()
    plan = _plan(manifest, ["o-1"])

    def review(manifest: ProcessingManifest, obligation_id: str) -> MethodResult:
        _add(manifest, _discovered())
        return MethodResult(success=False, validated=False, message="failed")

    registry = MethodRegistry()
    registry.register("human-review", review)
    executor = ExecutorAgent(registry, domain=DomainBundle.load())

    class Crash(BaseException):
        """A process death right after the step whose handler failed."""

    snapshots: list[dict] = []

    def save(snapshot: dict) -> None:
        snapshots.append(snapshot)
        if len(snapshot["results"]) == 2:
            raise Crash()

    with pytest.raises(Crash):
        executor.execute(plan, manifest, on_step=save)
    last = snapshots[-1]
    resume = ExecutionResume(
        manifest=ProcessingManifest.model_validate(last["manifest"]),
        results=[ExecutionStepResult.model_validate(item) for item in last["results"]],
        replan_required=last["replan_required"],
    )

    updated, report = executor.execute(plan, manifest, resume=resume)

    assert not next(item for item in updated.obligations if item.id == DISCOVERED).selected
    assert not report.replan_required
    assert DISCOVERED not in _replannable_obligation_ids(updated)


# --- in a job ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_restored_block_is_repaired_in_the_same_job(monkeypatch, tmp_path):
    """#594 acceptance: the rescue's new obligation is planned and run."""
    from types import SimpleNamespace

    from core_config_support import core_config
    from pddl_support import build_orchestrator
    from test_rescue_omitted_method import (
        LOWER,
        MIDDLE,
        _adopted,
        _manifest as rescue_manifest,
        _row,
    )

    from acessilia_core.agents.model_calls import current_model_calls
    from acessilia_core.pipeline import (
        orchestrator as pddl,
        preflight as pipeline_preflight,
    )
    from acessilia_core.pipeline.handlers import tables as table_method
    from acessilia_core.ports import RunPorts

    legacy = "The capital moved to Bras\u0131\u0301lia in the sixties."
    body = "The first paragraph of the body text."
    manifest = rescue_manifest(
        tmp_path,
        [_adopted("m-1", "paragraph", body, MIDDLE, 1)],
        replaced={1: [
            _row("d-1", "paragraph", body, MIDDLE, 1),
            _row("d-2", "paragraph", legacy, LOWER, 2),
        ]},
    )
    (tmp_path / "doc.pdf").write_bytes(b"%PDF-1.4\n")
    orchestrator = build_orchestrator(max_replans=1)
    orchestrator.information_structural = SimpleNamespace(process=lambda *a, **k: manifest)

    async def noop(*args, **kwargs):
        return None

    monkeypatch.setattr(pipeline_preflight, "inspect_source_media", noop)
    monkeypatch.setattr(pddl, "_enrich_picture_descriptions", noop)
    # The tables are read inside the plan, by ``table-enrichment`` (#640, M2).
    monkeypatch.setattr(table_method, "_enrich_table_structures", noop)

    payload = await orchestrator.execute(
        tmp_path / "doc.pdf", tmp_path, structured_output=True,
        config=core_config(document={"legacy_unicode_repair": "repair"}),
        model_calls=current_model_calls(), ports=RunPorts.none(),
    )

    assert payload["canonical_metadata"]["pddl_unsatisfied_obligations"] == []
    # The restored block reached the document, with its dotless i repaired.
    assert "capital moved to Bras" in payload["text"]
    assert "\u0131" not in payload["text"]


@pytest.mark.asyncio
async def test_a_restored_math_block_is_marked_after_the_replan(monkeypatch, tmp_path):
    """#599 through a real rescue, replan and second pass."""
    from types import SimpleNamespace

    from core_config_support import core_config
    from pddl_support import build_orchestrator
    from test_rescue_omitted_method import (
        LOWER,
        MIDDLE,
        _adopted,
        _manifest as rescue_manifest,
        _row,
    )

    from acessilia_core.agents.model_calls import current_model_calls
    from acessilia_core.pipeline import (
        orchestrator as pddl,
        preflight as pipeline_preflight,
    )
    from acessilia_core.pipeline.handlers import tables as table_method
    from acessilia_core.ports import RunPorts

    body = "The first paragraph of the body text."
    math = "The relation h = 0 holds."
    manifest = rescue_manifest(
        tmp_path,
        [_adopted("m-1", "paragraph", body, MIDDLE, 1)],
        replaced={1: [
            _row("d-1", "paragraph", body, MIDDLE, 1),
            _row("d-2", "paragraph", math, LOWER, 2),
        ]},
    )
    (tmp_path / "doc.pdf").write_bytes(b"%PDF-1.4\n")

    def span(value, font, x, baseline=450.0, size=11.96):
        width = max(len(value), 1) * size * 0.5
        return {
            "text": value, "font": font, "size": size, "flags": 4,
            "bbox": [x, baseline - size * 0.75, x + width, baseline + size * 0.25],
            "origin": [x, baseline],
        }

    async def fetch(source_path, pages, *, toolbox, artifact_id=None, client=None):
        return {1: {
            "page_number": 1, "width": 600.0, "height": 800.0, "rotation": 0,
            "lines": [{"bbox": [0, 0, 0, 0], "spans": [
                span("The relation ", "CMR12", 40),
                span("h", "CMMI12", 117.74),
                span("̸", "CMSY10", 123.72),
                span(" = 0", "CMR12", 123.72),
                span(" holds.", "CMR12", 147.64),
            ]}],
        }}

    monkeypatch.setattr("acessilia_core.toolbox.text_spans.fetch_text_spans", fetch)

    async def noop(*args, **kwargs):
        return None

    monkeypatch.setattr(pipeline_preflight, "inspect_source_media", noop)
    monkeypatch.setattr(pddl, "_enrich_picture_descriptions", noop)
    monkeypatch.setattr(table_method, "_enrich_table_structures", noop)

    orchestrator = build_orchestrator(max_replans=1)
    orchestrator.information_structural = SimpleNamespace(process=lambda *a, **k: manifest)
    payload = await orchestrator.execute(
        tmp_path / "doc.pdf", tmp_path, structured_output=True,
        config=core_config(document={"legacy_unicode_repair": "off"}),
        model_calls=current_model_calls(), ports=RunPorts.none(),
    )

    assert "The relation $h\\neq0$ holds." in payload["text"]
    blocks = [block for page in payload["pages"] for block in page["blocks"]]
    restored = next(block for block in blocks if "relation" in str(block.get("text")))
    assert restored["text"] == r"The relation $h\neq0$ holds."
    assert restored["metadata"]["inline_math_detection"] == {"marked": 1, "unmatched": 0}
