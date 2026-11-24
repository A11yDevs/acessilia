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
from pddl_support import build_element, build_manifest, build_obligation

from acessilia_core.agents.output_schemas import DataOutput
from acessilia_core.manifest.models import PageDescriptor
from acessilia_core.pipeline.enrichment import tables as table_stage
from acessilia_core.pipeline.enrichment.common import run_breaker
from acessilia_core.pipeline.enrichment.inline_math import run_text_spans
from acessilia_core.pipeline.handlers import tables as table_method
from acessilia_core.pipeline.obligations import (
    TABLE_ENRICHMENT_KIND,
    TABLE_ENRICHMENT_METHOD,
    TABLE_ENRICHMENT_OBLIGATION_ID,
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


def test_the_method_uses_the_run_breaker_and_span_reader(monkeypatch) -> None:
    """The same objects the enrichment before planning gets from the run's ports."""
    seen: dict[str, object] = {}

    async def read(manifest, source, *, breaker, **_kwargs):
        seen["breaker"] = breaker
        return 0

    async def mark(manifest, source, document, text_spans):
        seen["text_spans"] = text_spans
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
