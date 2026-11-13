"""How a table without a usable structure gets one (#402).

Characterization written on develop before ``_enrich_table_structures`` was
split. The crop and the data agent are replaced. tests/test_table_visual_review.py
covers the re-reading of misread tables; this file covers the other paths.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from backend.agents import pddl_orchestrator as pddl
from backend.agents.output_schemas import DataOutput
from backend.config.settings import settings
from backend.core.manifest.models import PageDescriptor
from tests.pddl_support import build_element, build_manifest
from backend.core.pipeline.enrichment import tables as table_stage


def _reading(rows, *, warnings=()):
    return DataOutput(
        kind="table",
        rows=[{"cells": [{"text": text, "scope": "col" if index == 0 else "none"} for text in row]}
              for index, row in enumerate(rows)],
        language="pt-BR", confidence=0.85, warnings=list(warnings),
    )


@pytest.fixture
def run(monkeypatch):
    monkeypatch.setattr(settings, "table_visual_review", True)
    monkeypatch.setattr(settings, "vision_retry_pass_delay_seconds", 0)

    def go(elements, answers, *, crops=None, pages=1, breaker=None):
        calls = []

        class Agent:
            async def process_region(self, **kwargs):
                calls.append(kwargs["fallback_text"])
                queue = answers.setdefault("_queue", list(answers.get("all", [])))
                return queue.pop(0) if queue else None

        async def run_inline(function, *args):
            return function(*args)

        monkeypatch.setattr(table_stage, "DataAgent", Agent)
        monkeypatch.setattr(table_stage, "_extract_picture_bytes",
                            lambda source, element, fallback, *rest: (crops or {}).get(element.id, (b"img", fallback or 1)))
        monkeypatch.setattr(pddl.asyncio, "to_thread", run_inline)
        manifest = build_manifest(elements, [])
        manifest.pages = [PageDescriptor(page_number=n, width=600.0, height=800.0, element_ids=[]) for n in range(1, pages + 1)]
        asyncio.run(table_stage._enrich_table_structures(manifest, Path("/tmp/doc.pdf"), breaker=breaker))
        return manifest, calls

    return go


def test_a_table_without_structure_is_read_and_its_metadata_written(run) -> None:
    table = build_element("t", "table", text="algo que o extrator leu")
    table.page_number = None

    manifest, calls = run([table], {"all": [_reading([["Nome", "Nota"], ["Ana", "9"]], warnings=["borrado"])]})

    md = table.metadata
    assert calls == ["algo que o extrator leu"]
    assert md["table_linearization_hint"] == "data-agent-structured"
    assert (md["table_row_count"], md["table_column_count"], md["table_has_header"]) == (2, 2, True)
    assert (md["data_language"], md["data_confidence"], md["data_warnings"]) == ("pt-BR", 0.85, ["borrado"])
    assert md["table_ast"]["body"]
    assert table.text == "" and table.page_number == 1
    assert "table_read_failure" not in md


def test_a_table_with_rows_in_its_own_text_needs_no_reading(run) -> None:
    table = build_element("t", "table", text="Nome;Nota\nAna;9\nBeto;8")

    _, calls = run([table], {})

    assert calls == []
    assert table.metadata["table_linearization_hint"] == "text-heuristic"


def test_an_answer_that_is_not_a_table_clears_an_earlier_failure(run) -> None:
    table = build_element("t", "table", text="", metadata={"table_read_failure": "model_failed"})
    formula = DataOutput(kind="formula", rows=[], language="und", confidence=0.5, latex="x")

    _, calls = run([table], {"all": [formula]})

    assert len(calls) == 1
    assert "table_read_failure" not in table.metadata
    assert "table_ast" not in table.metadata


def test_no_answer_is_a_model_failure_and_is_tried_once_more(run) -> None:
    table = build_element("t", "table", text="")

    _, calls = run([table], {"all": [None, _reading([["a", "b"], ["c", "d"]])]})

    assert len(calls) == 2
    assert table.metadata["table_row_count"] == 2
    assert "table_read_failure" not in table.metadata


def test_no_image_is_a_crop_failure_and_is_not_retried(run) -> None:
    table = build_element("t", "table", text="")

    _, calls = run([table], {}, crops={"t": (None, 1)})

    assert calls == []
    assert table.metadata["table_read_failure"] == "crop_unavailable"


def test_a_breaker_that_opens_between_readings_stops_the_rereads(run) -> None:
    rows = [["Prefix", "symbol"], ["yota zeta exa peta tera", "Y Z E P T"]]
    misread = build_element("m", "table", metadata={"table_ast": {
        "header": [{"cells": [{"text": text, "scope": "col"} for text in rows[0]]}],
        "body": [{"cells": [{"text": text} for text in rows[1]]}],
    }})
    breaker = pddl.ProviderBreaker(1)

    _, calls = run([misread], {"all": [None]}, breaker=breaker)

    review = misread.metadata.get("table_review")
    assert len(calls) == 2  # one on the first pass, the retry pass's probe
    assert review is not None and review["outcome"] == "kept"
    assert misread.metadata["table_read_failure"] == "model_failed"
