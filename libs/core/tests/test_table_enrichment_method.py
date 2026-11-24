"""The document's table enrichment as a planned action (#640, M2).

Until 0.3.11 the orchestrator read the tables and marked their inline math
before planning. Now an ``enrich-tables`` obligation, added when the document
has tables, is satisfied by the ``table-enrichment`` method, which runs the
same two steps. These tests pin the obligation, its place in the plan, the
method, and its equivalence with the steps it replaces.
"""

from __future__ import annotations

import asyncio
from copy import deepcopy
from pathlib import Path

import pytest
from core_config_support import core_config
from pddl_support import (
    build_element,
    build_manifest,
    build_obligation,
    build_orchestrator,
)
from test_table_inline_math_marking import (
    _manifest as _math_manifest,
    spans,  # noqa: F401  (fixture)
)

from acessilia_core.agents.model_calls import ModelCallRejected
from acessilia_core.agents.output_schemas import DataOutput
from acessilia_core.i18n import n, t
from acessilia_core.i18n.stage_messages import (
    STAGE_ENRICHING_TABLES_OCR,
    STAGE_PAGES,
    STAGE_PAGES_SPAN,
)
from acessilia_core.manifest.models import PageDescriptor
from acessilia_core.pipeline.enrichment import tables as table_stage
from acessilia_core.pipeline.enrichment.common import run_breaker
from acessilia_core.pipeline.enrichment.inline_math import run_text_spans
from acessilia_core.pipeline.handlers import tables as table_method
from acessilia_core.pipeline.handlers.messages import (
    MSG_TABLE_NO_TABLE,
    MSG_TABLES_ENRICHED,
)
from acessilia_core.pipeline.handlers.registry import bind_run, build_method_registry
from acessilia_core.pipeline.obligations import (
    TABLE_ENRICHMENT_KIND,
    TABLE_ENRICHMENT_METHOD,
    TABLE_ENRICHMENT_OBLIGATION_ID,
    _pages_label,
    add_table_enrichment_obligation,
)
from acessilia_core.planning.planner_agent import PlannerAgent
from acessilia_core.ports import RunPorts

CONFIG = core_config(vision={"table_visual_review": True, "retry_pass_delay_seconds": 0})
_STRUCTURED = {"body": [{"cells": [{"text": "Value"}]}]}


def _reading(rows):
    return DataOutput(
        kind="table",
        rows=[{"cells": [{"text": text, "scope": "col" if index == 0 else "none"} for text in row]}
              for index, row in enumerate(rows)],
        language="pt-BR", confidence=0.85, warnings=[],
    )


def _tables_manifest():
    unread = build_element("t-1", "table", text="algo que o extrator leu")
    read = build_element("t-2", "table", metadata={"table_ast": deepcopy(_STRUCTURED)})
    paragraph = build_element("p-1", "paragraph", text="texto")
    obligations = [
        build_obligation("linearize-table", ["t-1"], ["pandoc-table", "human-review"]),
        build_obligation("linearize-table", ["t-2"], ["pandoc-table", "human-review"]),
        build_obligation("select-table-source", ["t-1"], ["table-smart-fusion", "human-review"]),
        build_obligation("review-structure", ["p-1"], ["human-review"]),
    ]
    for index, obligation in enumerate(obligations, start=1):
        obligation.id = f"o-{index}"
    manifest = build_manifest([unread, read, paragraph], obligations)
    manifest.pages = [PageDescriptor(page_number=1, width=600.0, height=800.0, element_ids=[])]
    return manifest


FONTS = core_config(
    vision={"table_visual_review": True, "retry_pass_delay_seconds": 0},
    document={"inline_math_detection": "fonts"},
)


def _answers(monkeypatch, answers):
    """The data agent answers the tables in order: a reading, ``None`` (no
    answer) or an exception to raise."""
    calls: list[str] = []
    queue = list(answers)

    class Agent:
        def __init__(self, **_kwargs):
            pass

        async def process_region(self, **kwargs):
            calls.append(kwargs["fallback_text"])
            answer = queue.pop(0) if queue else None
            if isinstance(answer, Exception):
                raise answer
            return answer

    monkeypatch.setattr(table_stage, "DataAgent", Agent)
    monkeypatch.setattr(
        table_stage, "_extract_picture_bytes",
        lambda source, element, fallback, *rest, **_kwargs: (b"img", fallback or 1),
    )
    return calls


def _in_executor(manifest, config, ports):
    """Plan and execute ``manifest`` as a run does: the executor works on a copy."""
    add_table_enrichment_obligation(manifest)
    executor = build_orchestrator().executor
    executor.registry = bind_run(build_method_registry(), config, ports)
    _, plan = PlannerAgent().plan(manifest)
    return executor.execute(plan, manifest)


@pytest.fixture
def fake_reader(monkeypatch):
    """The data agent answers every table it is asked to read with one table."""
    calls: list[str] = []

    class Agent:
        def __init__(self, **_kwargs):
            pass

        async def process_region(self, **kwargs):
            calls.append(kwargs["fallback_text"])
            return _reading([["Nome", "Nota"], ["Ana", "9"]])

    monkeypatch.setattr(table_stage, "DataAgent", Agent)
    monkeypatch.setattr(
        table_stage, "_extract_picture_bytes",
        lambda source, element, fallback, *rest, **_kwargs: (b"img", fallback or 1),
    )
    return calls


# The obligation.


def test_a_document_without_tables_gets_no_obligation() -> None:
    manifest = build_manifest([build_element("p", "paragraph", text="texto")], [])

    assert add_table_enrichment_obligation(manifest) is None
    assert manifest.obligations == []


def test_the_obligation_covers_every_table_and_precedes_their_obligations() -> None:
    manifest = _tables_manifest()

    obligation = add_table_enrichment_obligation(manifest)

    assert obligation is not None
    assert obligation.id == TABLE_ENRICHMENT_OBLIGATION_ID
    assert obligation.kind == TABLE_ENRICHMENT_KIND
    assert obligation.target_ids == ["t-1", "t-2"]
    assert obligation.admissible_methods == [TABLE_ENRICHMENT_METHOD, "human-review"]
    assert manifest.summary.obligation_count == len(manifest.obligations)
    by_kind = {(item.kind, tuple(item.target_ids)): item for item in manifest.obligations}
    assert by_kind[("linearize-table", ("t-1",))].dependencies == [obligation.id]
    assert by_kind[("linearize-table", ("t-2",))].dependencies == [obligation.id]
    assert by_kind[("select-table-source", ("t-1",))].dependencies == [obligation.id]
    assert by_kind[("review-structure", ("p-1",))].dependencies == []


def test_adding_the_obligation_twice_changes_nothing() -> None:
    manifest = _tables_manifest()
    first = add_table_enrichment_obligation(manifest)
    before = manifest.model_dump()

    assert add_table_enrichment_obligation(manifest) is first
    assert manifest.model_dump() == before


def test_the_plan_enriches_the_tables_before_it_linearizes_them() -> None:
    manifest = _tables_manifest()
    add_table_enrichment_obligation(manifest)

    _, plan = PlannerAgent().plan(manifest)

    order = [step.obligation_id for step in plan.steps if step.method]
    enrich = order.index(TABLE_ENRICHMENT_OBLIGATION_ID)
    assert all(
        order.index(item.id) > enrich
        for item in manifest.obligations
        if item.kind in {"linearize-table", "select-table-source"}
    )


# The method.


def test_the_method_reads_the_unreadable_tables_and_reports_them(fake_reader) -> None:
    manifest = _tables_manifest()
    obligation = add_table_enrichment_obligation(manifest)

    result = table_method._handle_table_enrichment_method(
        manifest, obligation.id, config=CONFIG, ports=RunPorts.none()
    )

    assert result.success and result.validated
    assert fake_reader == ["algo que o extrator leu"]  # only the table without a structure
    assert "2" in result.message and "1" in result.message


def test_the_method_without_tables_fails_instead_of_raising() -> None:
    manifest = build_manifest([build_element("p", "paragraph", text="texto")], [])

    result = table_method._handle_table_enrichment_method(
        manifest, "obligation-enrich-tables", config=CONFIG, ports=RunPorts.none()
    )

    assert not result.success


def test_an_obligation_without_table_targets_says_so() -> None:
    """The obligation exists; it has no table to enrich (review of #833)."""
    obligation = build_obligation(TABLE_ENRICHMENT_KIND, ["p"], [TABLE_ENRICHMENT_METHOD])
    manifest = build_manifest([build_element("p", "paragraph", text="texto")], [obligation])

    result = table_method._handle_table_enrichment_method(
        manifest, obligation.id, config=CONFIG, ports=RunPorts.none()
    )

    assert not result.success
    assert result.message == t(MSG_TABLE_NO_TABLE)


# What the result reports (review of #833): the collective attempt ran, and
# each table keeps its own outcome.


def _two_unread_tables():
    manifest = build_manifest(
        [build_element("t-1", "table", text="primeira"), build_element("t-2", "table", text="segunda")],
        [],
    )
    manifest.pages = [PageDescriptor(page_number=1, width=600.0, height=800.0, element_ids=[])]
    return manifest


@pytest.mark.parametrize(
    ("answers", "structured", "left"),
    [
        pytest.param([_reading([["A", "B"], ["1", "2"]])] * 2, 2, "-", id="all-read"),
        pytest.param([_reading([["A", "B"], ["1", "2"]]), None, None], 1, "model_failed: 1", id="partial"),
        pytest.param([None, None, None, None], 0, "model_failed: 2", id="all-failed"),
    ],
)
def test_the_method_succeeds_and_reports_each_table(monkeypatch, answers, structured, left) -> None:
    _answers(monkeypatch, answers)
    manifest = _two_unread_tables()
    obligation = add_table_enrichment_obligation(manifest)

    result = table_method._handle_table_enrichment_method(
        manifest, obligation.id, config=CONFIG, ports=RunPorts.none()
    )

    assert result.success and result.validated
    assert f"2 needed a reading, {structured} got a structure" in result.message
    assert f"left as they were: {left}" in result.message
    failures = [element.metadata.get("table_read_failure") for element in manifest.elements]
    assert failures.count("model_failed") == (2 - structured)


def test_nothing_to_read_calls_no_model(monkeypatch) -> None:
    calls = _answers(monkeypatch, [])
    manifest = _tables_manifest()
    manifest.elements[0].metadata["table_ast"] = deepcopy(_STRUCTURED)
    obligation = add_table_enrichment_obligation(manifest)

    result = table_method._handle_table_enrichment_method(
        manifest, obligation.id, config=CONFIG, ports=RunPorts.none()
    )

    assert calls == []
    assert "0 needed a reading" in result.message


def test_an_admission_rejection_keeps_its_reason_and_spares_the_breaker(monkeypatch) -> None:
    """#590 with #833: inside the plan, a full model-call runner is recorded as
    ``admission_rejected`` on the manifest the executor returns, and does not
    count against the provider (a breaker of threshold 1 would open)."""
    config = core_config(vision={"breaker_threshold": 1, "retry_pass_delay_seconds": 0})
    _answers(monkeypatch, [ModelCallRejected("full")] * 4)
    manifest = _two_unread_tables()
    ports = RunPorts.none()

    executed, report = _in_executor(manifest, config, ports)

    failures = {e.id: e.metadata.get("table_read_failure") for e in executed.elements}
    assert failures == {"t-1": "admission_rejected", "t-2": "admission_rejected"}
    assert run_breaker(ports, config.vision).open is False
    enrich = next(item for item in executed.obligations if item.kind == TABLE_ENRICHMENT_KIND)
    assert enrich.status == "satisfied"
    assert "admission_rejected: 2" in enrich.attempts[-1].message


def test_unavailable_text_spans_reach_the_manifest_the_executor_returns(monkeypatch) -> None:
    """The span reader was built before planning with another manifest; the
    executor's copy still records the inline math as unavailable."""
    from acessilia_sdk.toolbox.errors import ToolboxError

    async def failing(*_args, **_kwargs):
        raise ToolboxError("document.text.spans is down")

    monkeypatch.setattr("acessilia_core.toolbox.text_spans.fetch_text_spans", failing)
    manifest = _math_manifest()
    ports = RunPorts.none()
    run_text_spans(ports, deepcopy(manifest), Path(manifest.source.path), FONTS.toolbox)

    executed, _ = _in_executor(manifest, FONTS, ports)

    assert executed.extractor.configuration["inline_math_detection"] == "unavailable"


def test_the_method_marks_the_inline_math_as_the_steps_before_planning_did(spans) -> None:  # noqa: F811
    """The differential test with the inline math detection on."""
    before = _math_manifest()
    after = deepcopy(before)
    source = Path(before.source.path)

    async def steps_before_planning():
        ports = RunPorts.none()
        await table_method._mark_table_inline_math(
            before, source, FONTS.document, run_text_spans(ports, before, source, FONTS.toolbox)
        )

    asyncio.run(steps_before_planning())
    obligation = add_table_enrichment_obligation(after)
    result = table_method._handle_table_enrichment_method(
        after, obligation.id, config=FONTS, ports=RunPorts.none()
    )

    assert [e.model_dump() for e in after.elements] == [e.model_dump() for e in before.elements]
    assert "$" in str(after.elements[1].metadata["table_ast"])  # the marks did run
    assert "inline math: fonts" in result.message


def test_the_method_reports_its_progress_through_the_run(fake_reader) -> None:
    messages: list[str] = []
    ports = RunPorts.none()
    ports.services.progress = messages.append
    manifest = _tables_manifest()
    obligation = add_table_enrichment_obligation(manifest)

    table_method._handle_table_enrichment_method(manifest, obligation.id, config=CONFIG, ports=ports)

    assert messages[0] == t(STAGE_ENRICHING_TABLES_OCR)
    assert any(message.startswith("Recognizing table 1 of 1") for message in messages[1:])


def test_a_step_over_many_pages_gives_their_span() -> None:
    assert _pages_label([1, 3, 5, 7, 9], 10) == t(STAGE_PAGES).format(pages="1, 3, 5, 7, 9")
    assert _pages_label(range(1, 13), 20) == t(STAGE_PAGES_SPAN).format(count=12, first=1, last=12)


def test_the_method_uses_the_run_breaker_and_span_reader(monkeypatch) -> None:
    """The same objects the enrichment before planning gets from the run's ports."""
    seen: dict[str, object] = {}

    async def read(manifest, source, *, breaker, targets, **_kwargs):
        seen["breaker"] = breaker
        seen["read_targets"] = targets
        return 0

    async def mark(manifest, source, document, text_spans, *, targets):
        seen["text_spans"] = text_spans
        seen["mark_targets"] = targets
        return {"elements": 0, "marked": 0, "unmatched": 0}

    monkeypatch.setattr(table_method, "_enrich_table_structures", read)
    monkeypatch.setattr(table_method, "_mark_table_inline_math", mark)
    manifest = _tables_manifest()
    obligation = add_table_enrichment_obligation(manifest)
    ports = RunPorts.none()
    source = Path(manifest.source.path)

    table_method._handle_table_enrichment_method(manifest, obligation.id, config=CONFIG, ports=ports)

    assert seen["breaker"] is run_breaker(ports, CONFIG.vision)
    assert seen["text_spans"] is run_text_spans(ports, manifest, source, CONFIG.toolbox)
    assert seen["read_targets"] == seen["mark_targets"] == frozenset(obligation.target_ids)


def test_each_run_has_its_own_breaker() -> None:
    assert run_breaker(RunPorts.none(), CONFIG.vision) is not run_breaker(RunPorts.none(), CONFIG.vision)


# Equivalence with the steps before planning (ADR-0028: a differential test).


def test_the_method_leaves_the_tables_as_the_steps_before_planning_did(fake_reader) -> None:
    before = _tables_manifest()
    after = deepcopy(before)
    source = Path(before.source.path)

    # As the orchestrator ran them until 0.3.11: read, then mark.
    async def steps_before_planning():
        ports = RunPorts.none()
        await table_stage._enrich_table_structures(
            before, source, vision=CONFIG.vision, toolbox=CONFIG.toolbox, models=CONFIG.models,
            breaker=run_breaker(ports, CONFIG.vision),
        )
        await table_method._mark_table_inline_math(
            before, source, CONFIG.document, run_text_spans(ports, before, source, CONFIG.toolbox)
        )

    asyncio.run(steps_before_planning())
    obligation = add_table_enrichment_obligation(after)
    table_method._handle_table_enrichment_method(after, obligation.id, config=CONFIG, ports=RunPorts.none())

    def tables(manifest):
        return [element.model_dump() for element in manifest.elements]

    assert tables(after) == tables(before)
    assert after.extractor.configuration == before.extractor.configuration
    assert len(fake_reader) == 2  # one reading per path


# Resume across the migration (review of #833).


def _ctx(enriched_state):
    from types import SimpleNamespace

    saved: dict = {}

    class Checkpoints:
        def load(self, phase):
            return enriched_state

        async def save(self, phase, build):
            saved[phase] = build()

    return SimpleNamespace(
        checkpoints=Checkpoints(), effective_mode="medio", config=CONFIG, ports=RunPorts.none(),
        source_path=Path("/tmp/doc.pdf"), status_callback=None,
    ), saved


@pytest.mark.parametrize("with_obligation", [False, True], ids=["0.3.11", "0.3.12"])
def test_an_enrichment_checkpoint_is_resumed_as_it_was(monkeypatch, with_obligation) -> None:
    """A 0.3.11 checkpoint already has its tables enriched, so it gets no
    obligation; a 0.3.12 one keeps the obligation it has."""
    from acessilia_core.pipeline.checkpointing import manifest_payload

    checkpointed = _tables_manifest()
    if with_obligation:
        add_table_enrichment_obligation(checkpointed)
    ctx, _ = _ctx({"manifest": manifest_payload(checkpointed)})

    resumed = asyncio.run(
        build_orchestrator()._load_or_enrich_manifest(ctx, _tables_manifest(), None, {})
    )

    kinds = [item.kind for item in resumed.obligations]
    assert kinds.count(TABLE_ENRICHMENT_KIND) == (1 if with_obligation else 0)


def test_a_fresh_enrichment_adds_the_obligation_before_its_checkpoint(monkeypatch) -> None:
    async def no_enrichment(*_args, **_kwargs):
        return None

    orchestrator = build_orchestrator()
    monkeypatch.setattr(orchestrator, "_enrich_before_planning", no_enrichment)
    ctx, saved = _ctx(None)

    enriched = asyncio.run(orchestrator._load_or_enrich_manifest(ctx, _tables_manifest(), None, {}))

    assert any(item.kind == TABLE_ENRICHMENT_KIND for item in enriched.obligations)
    assert any(
        item["kind"] == TABLE_ENRICHMENT_KIND for item in next(iter(saved.values()))["manifest"]["obligations"]
    )


# The scope of a second enrichment (#832).


def test_a_second_enrichment_reads_only_its_own_tables(fake_reader) -> None:
    """``obligation-enrich-tables-2`` covers only the table found later. A
    table of the first enrichment that is still eligible for a reading (t-1
    has no structure) is neither read nor changed by the second."""
    manifest = _tables_manifest()
    first = add_table_enrichment_obligation(manifest)
    first.status = "satisfied"
    for item in manifest.obligations:
        if item.id != first.id and "t-1" not in item.target_ids:
            item.status = "satisfied"
    found = build_element("t-3", "table", text="a tabela encontrada depois")
    manifest.elements.append(found)
    manifest.summary.element_count = len(manifest.elements)
    t1_before = next(e for e in manifest.elements if e.id == "t-1").model_dump()
    second = add_table_enrichment_obligation(manifest, replan=True)
    assert second.target_ids == ["t-3"]

    result = table_method._handle_table_enrichment_method(
        manifest, second.id, config=CONFIG, ports=RunPorts.none()
    )

    assert fake_reader == ["a tabela encontrada depois"]
    assert next(e for e in manifest.elements if e.id == "t-1").model_dump() == t1_before
    assert "table_ast" in found.metadata
    assert result.message == n(*MSG_TABLES_ENRICHED, 1).format(
        count=1, needing=1, structured=1, left="-",
        inline=table_method._inline_math_status(manifest, CONFIG), marked=0,
    )


def test_the_marks_keep_to_the_obligation_tables(spans) -> None:  # noqa: F811
    """The inline math of a table is marked only by its own enrichment."""
    outside = _math_manifest()
    inside = _math_manifest()
    source = Path(outside.source.path)

    async def mark(manifest, targets):
        ports = RunPorts.none()
        return await table_method._mark_table_inline_math(
            manifest, source, FONTS.document,
            run_text_spans(ports, manifest, source, FONTS.toolbox), targets=targets,
        )

    assert asyncio.run(mark(outside, frozenset({"another-table"})))["marked"] == 0
    assert "$" not in str(outside.elements[1].metadata["table_ast"])
    assert asyncio.run(mark(inside, frozenset({"t1"})))["marked"] > 0
    assert "$" in str(inside.elements[1].metadata["table_ast"])
