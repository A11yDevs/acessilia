"""Inline math in table cells and captions reaches every export as math (#260)."""
import json

from backend.pipeline.pandoc_ast_builder import build_pandoc_ast, degrade_math_to_text
from docstruct.canonical import _enrich_math_blocks
from docstruct.export.html import document_to_html
from docstruct.export.txt import document_to_txt_lines
from docstruct.text.math_spans import block_prose

MATHML = '<math xmlns="http://www.w3.org/1998/Math/MathML"><mi>h</mi></math>'
FRACTION = r"\frac{s(3+h)-s(3)}{(3+h)-3}"
ENTRIES = [
    {"source": r"h \neq 0", "latex": r"h \neq 0", "mathml": MATHML, "speech": "h not equal to zero"},
    {"source": FRACTION, "latex": FRACTION, "speech": "a fraction"},
    {"source": "-0{,}0833", "latex": "-0{,}0833", "speech": "minus zero point zero eight three three"},
]


class _Enricher:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def normalize(self, latex: str) -> str:
        return latex

    def to_mathml(self, latex: str) -> str:
        self.calls.append(latex)
        return MATHML

    def verbalize(self, latex: str) -> str:
        return latex

    def verbalize_inline(self, latex: str) -> str:
        return f"speech of {latex}"


def _table(**metadata):
    return {
        "id": "t1",
        "type": "table",
        "table_ast": {
            "caption": "Mean speed with $h \\neq 0$",
            "header": [
                {
                    "cells": [
                        {"text": "$h \\neq 0$"},
                        {"text": f"mean speed ${FRACTION}$"},
                    ]
                }
            ],
            "body": [
                {"cells": [{"text": "1"}, {"text": "$-0{,}0833$ (approximately)"}]},
                {"cells": [{"text": "0,1"}, {"text": ""}]},
            ],
        },
        "metadata": metadata,
    }


def _document(block):
    return {"title": "", "sections": [{"id": "s1", "title": "", "blocks": [block], "children": []}]}


def test_table_prose_is_its_caption_and_cells():
    assert block_prose(_table()) == [
        "Mean speed with $h \\neq 0$",
        "$h \\neq 0$",
        f"mean speed ${FRACTION}$",
        "1",
        "$-0{,}0833$ (approximately)",
        "0,1",
    ]


def test_enrichment_converts_the_cells_spans_on_the_block():
    block = _table()
    enricher = _Enricher()

    _enrich_math_blocks(_document(block)["sections"], enricher)

    sources = [entry["source"] for entry in block["metadata"]["inline_math"]]
    assert sources == [r"h \neq 0", FRACTION, "-0{,}0833"]
    assert enricher.calls == sources


def test_html_renders_cell_and_caption_math():
    html = document_to_html(_document(_table(inline_math=ENTRIES)))

    assert f'<caption>Mean speed with <span role="math" aria-label="h not equal to zero">{MATHML}</span></caption>' in html
    assert f'<th scope="col"><span role="math" aria-label="h not equal to zero">{MATHML}</span></th>' in html
    assert f'mean speed <span role="math" aria-label="a fraction">{FRACTION}</span>' in html
    assert '<span role="math" aria-label="minus zero point zero eight three three">-0{,}0833</span> (approximately)</td>' in html
    assert "$" not in html


def test_html_without_enrichment_keeps_the_latex_marked_as_math():
    html = document_to_html(_document(_table()))

    assert '<td><span role="math">-0{,}0833</span> (approximately)</td>' in html


def test_pandoc_ast_emits_inline_math_in_cells_and_caption():
    ast = build_pandoc_ast(_document(_table(inline_math=ENTRIES)))

    table = next(block for block in ast["blocks"] if block["t"] == "Table")
    payload = json.dumps(table, ensure_ascii=False)
    assert "$" not in payload
    for entry in ENTRIES:
        assert json.dumps({"t": "Math", "c": [{"t": "InlineMath"}, entry["latex"]]}) in json.dumps(table)
        assert json.dumps(["alt", entry["speech"]], ensure_ascii=False) in payload
    short_caption = table["c"][1][0]
    assert short_caption[-1]["t"] == "Span"


def test_degrading_removes_the_cells_math():
    degraded = degrade_math_to_text(build_pandoc_ast(_document(_table(inline_math=ENTRIES))))

    assert "Math" not in json.dumps(degraded["blocks"])
    assert "-0{,}0833" in json.dumps(degraded["blocks"])


def test_txt_reads_the_cells_math():
    lines = document_to_txt_lines(_document(_table(inline_math=ENTRIES)))
    text = "\n".join(lines)

    assert "h not equal to zero" in text
    assert "mean speed a fraction" in text
    assert "minus zero point zero eight three three (approximately)" in text
    assert "$" not in text


def test_txt_without_enrichment_drops_the_delimiters():
    text = "\n".join(document_to_txt_lines(_document(_table())))

    assert "-0{,}0833 (approximately)" in text
    assert "$" not in text


def test_table_from_rows_also_renders_math():
    block = {"id": "t1", "type": "table", "rows": [["h", "v"], ["1", "$-2$"]]}

    assert '<span role="math">-2</span>' in document_to_html(_document(block))
    assert "$" not in "\n".join(document_to_txt_lines(_document(block)))
