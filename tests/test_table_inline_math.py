"""Inline math in table cells and captions reaches every export as math (#260)."""
import json
import re

from backend.pipeline.pandoc_ast_builder import build_pandoc_ast, degrade_math_to_text
from docstruct.canonical import _enrich_math_blocks, build_canonical_document, sanitize_canonical_document
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


def _table_html(html: str) -> str:
    return re.search(r"<table.*?</table>", html, re.DOTALL).group(0)


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
    assert "$" not in _table_html(html)


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


def test_txt_does_not_mutate_the_table_block():
    block = _table(inline_math=ENTRIES)

    document_to_txt_lines(_document(block))

    assert block["table_ast"]["body"][0]["cells"][1]["text"] == "$-0{,}0833$ (approximately)"
    assert block["table_ast"]["caption"] == "Mean speed with $h \\neq 0$"


def test_pandoc_ast_keeps_an_unsafe_cell_span_as_text():
    block = {"id": "t1", "type": "table", "table_ast": {"body": [{"cells": [{"text": r"veja $\input{x}$"}]}]}}

    table = next(item for item in build_pandoc_ast(_document(block))["blocks"] if item["t"] == "Table")

    assert "Math" not in json.dumps(table)


def test_cell_fallbacks_use_the_normalized_latex():
    entry = {"source": r"\text{x}", "latex": "x"}
    block = {
        "id": "t1",
        "type": "table",
        "table_ast": {"body": [{"cells": [{"text": r"seja $\text{x}$"}]}]},
        "metadata": {"inline_math": [entry]},
    }
    document = _document(block)

    assert '<td>seja <span role="math">x</span></td>' in document_to_html(document)
    assert "seja x" in "\n".join(document_to_txt_lines(document))
    table = next(item for item in build_pandoc_ast(document)["blocks"] if item["t"] == "Table")
    assert json.dumps({"t": "Math", "c": [{"t": "InlineMath"}, "x"]}) in json.dumps(table)


def test_sanitized_canonical_document_still_renders_the_cells_math():
    """The export sanitizer rebuilds every cell dict, so the entries must
    survive on the block (backend ``_ensure_document`` path)."""
    payload = {"pages": [{"blocks": [{"id": "t1", "type": "table", "table_ast": _table()["table_ast"]}]}]}
    document = sanitize_canonical_document(build_canonical_document(payload, title="t", math_enricher=_Enricher()))

    html = document_to_html(document)
    assert f'<th scope="col"><span role="math" aria-label="speech of h \\neq 0">{MATHML}</span></th>' in html
    assert "$" not in _table_html(html)
    assert "$" not in "\n".join(document_to_txt_lines(document))
    table = next(item for item in build_pandoc_ast(document)["blocks"] if item["t"] == "Table")
    assert "$" not in json.dumps(table)
    assert "InlineMath" in json.dumps(table)


def test_txt_without_enrichment_drops_the_delimiters():
    text = "\n".join(document_to_txt_lines(_document(_table())))

    assert "-0{,}0833 (approximately)" in text
    assert "$" not in text


def test_table_from_rows_also_renders_math():
    block = {"id": "t1", "type": "table", "rows": [["h", "v"], ["1", "$-2$"]]}

    assert '<span role="math">-2</span>' in document_to_html(_document(block))
    assert "$" not in "\n".join(document_to_txt_lines(_document(block)))
