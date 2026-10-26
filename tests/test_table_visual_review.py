"""A table read in the wrong shape is read again from its image.

006.pdf slide 5 came back with each prefix table collapsed into one row of
ten values per cell, and slide 15 with every cell of the chlorine isotope
table doubled. Both had structure, so the table enrichment never looked at
them again.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from backend.agents.output_schemas import DataOutput
from backend.agents.pddl_orchestrator import _enrich_table_structures
from backend.config.settings import settings
from tests.pddl_support import build_element as _element
from tests.pddl_support import build_manifest as _manifest


def _ast(rows: list[list[str]]) -> dict:
    header, *body = rows
    return {
        "header": [{"cells": [{"text": text, "scope": "col"} for text in header]}],
        "body": [{"cells": [{"text": text} for text in row]} for row in body],
    }


#: 006.pdf slide 5, the table of multiples as the extractor read it.
COLLAPSED = [
    ["Prefix", "symbol", "power"],
    [
        "yota zeta exa peta tera giga mega kilo hecto deca",
        "Y Z E P T G M k h da",
        "10^24 10^21 10^18 10^15 10^12 10^9 10^6 10^3 10^2 10^1",
    ],
]

PREFIXES = [
    ("yota", "Y", "10^24"), ("zeta", "Z", "10^21"), ("exa", "E", "10^18"),
    ("peta", "P", "10^15"), ("tera", "T", "10^12"), ("giga", "G", "10^9"),
    ("mega", "M", "10^6"), ("kilo", "k", "10^3"), ("hecto", "h", "10^2"),
    ("deca", "da", "10^1"),
]


def _reading(rows: list[list[str]]) -> DataOutput:
    return DataOutput(
        kind="table",
        rows=[
            {"cells": [{"text": text, "scope": "col" if index == 0 else "none"} for text in row]}
            for index, row in enumerate(rows)
        ],
        language="pt-BR",
        confidence=0.9,
    )


def _run(monkeypatch, rows, reading):
    """Enrich a table read as ``rows``; ``reading`` answers every call, or each
    call in turn when it is a list."""
    from backend.agents import pddl_orchestrator as pddl_module

    table = _element("t-1", "table", metadata={"table_ast": _ast(rows)})
    manifest = _manifest([table], [])
    calls = []

    class FakeDataAgent:
        async def process_region(self, **kwargs):
            calls.append(kwargs)
            if isinstance(reading, list):
                return reading[min(len(calls), len(reading)) - 1]
            return reading

    async def run_inline(function, *args):
        return function(*args)

    monkeypatch.setattr(pddl_module, "DataAgent", FakeDataAgent)
    monkeypatch.setattr(pddl_module, "_extract_picture_bytes", lambda *_args: (b"image", 1))
    monkeypatch.setattr(pddl_module.asyncio, "to_thread", run_inline)
    asyncio.run(_enrich_table_structures(manifest, Path("/tmp/deck.pdf")))
    return table, calls


def _body(table) -> list[list[str]]:
    return [[cell["text"] for cell in row["cells"]] for row in table.metadata["table_ast"]["body"]]


def test_a_collapsed_table_is_replaced_by_its_reading_from_the_image(monkeypatch):
    reading = _reading([["Prefix", "symbol", "power"], *map(list, PREFIXES)])

    table, calls = _run(monkeypatch, COLLAPSED, reading)

    assert len(calls) == 1
    assert len(_body(table)) == 10
    assert _body(table)[0] == ["yota", "Y", "10^24"]
    assert table.metadata["table_review"] == {
        "reason": "collapsed_rows", "outcome": "replaced", "attempts": 1,
    }
    assert table.metadata["table_ast_replaced"] == _ast(COLLAPSED)


def test_a_table_with_doubled_cells_is_read_again(monkeypatch):
    doubled = [
        ["Isotopes Isotopes", "Mass (u) Mass (u)", "Abundance (%) Abundance (%)"],
        ["35Cl 35Cl", "34.97 34.97", "75.76 75.76"],
        ["37Cl 37Cl", "36.97 36.97", "24.24 24.24"],
    ]
    reading = _reading(
        [["Isotopes", "Mass (u)", "Abundance (%)"], ["35Cl", "34.97", "75.76"], ["37Cl", "36.97", "24.24"]]
    )

    table, _ = _run(monkeypatch, doubled, reading)

    assert _body(table) == [["35Cl", "34.97", "75.76"], ["37Cl", "36.97", "24.24"]]
    assert table.metadata["table_review"]["reason"] == "duplicated_cells"


@pytest.mark.parametrize(
    "rows, why",
    [
        (COLLAPSED, "misread too: collapsed_rows"),
        ([["Country", "Capital", "Currency"], ["Japan", "Tokyo", "Yen"]], "of its words"),
        # 006.pdf, one try: every cell of the table on a row of its own.
        ([[name] for prefix in PREFIXES for name in prefix], "1 column(s), the table 3"),
        # 006.pdf, another try: the header row and nothing else.
        ([["Prefix", "symbol", "power"], ["yota", "Y", "10^24"]], "keeps only"),
    ],
    ids=["misread-again", "another-table", "one-column", "header-only"],
)
def test_a_reading_that_is_not_the_same_table_read_better_is_not_used(monkeypatch, rows, why):
    table, _ = _run(monkeypatch, COLLAPSED, _reading(rows))

    assert table.metadata["table_ast"] == _ast(COLLAPSED)
    assert table.metadata["table_review"]["outcome"] == "kept"
    assert table.metadata["table_review"]["attempts"] == 3
    assert why in table.metadata["table_review"]["why"]


def test_a_misread_table_gets_another_reading_after_a_bad_one(monkeypatch):
    bad = _reading([["Prefix"], ["symbol"], ["power"]])
    good = _reading([["Prefix", "symbol", "power"], *map(list, PREFIXES)])

    table, calls = _run(monkeypatch, COLLAPSED, [bad, good])

    assert len(calls) == 2
    assert len(_body(table)) == 10
    assert table.metadata["table_review"]["attempts"] == 2


def test_a_table_read_well_is_not_read_again(monkeypatch):
    rows = [["Isotope", "Mass"], ["35Cl", "34.97"], ["37Cl", "36.97"]]

    table, calls = _run(monkeypatch, rows, _reading(rows))

    assert calls == []
    assert "table_review" not in table.metadata


def test_the_review_is_off_with_its_setting(monkeypatch):
    monkeypatch.setattr(settings, "table_visual_review", False)

    table, calls = _run(monkeypatch, COLLAPSED, _reading([["a"]]))

    assert calls == []
    assert table.metadata["table_ast"] == _ast(COLLAPSED)
