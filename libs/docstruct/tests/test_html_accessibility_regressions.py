"""Readable callouts and keyboard access to canonical tables."""
from copy import deepcopy
from xml.etree import ElementTree as ET

import pytest

from docstruct.blocks.callouts import dedupe_callout_titles
from docstruct.export.html import HtmlLabels, _render_block, document_to_html


@pytest.mark.parametrize("kind,tag", [("note", "aside"), ("warning", "aside"), ("quote", "blockquote")])
@pytest.mark.parametrize("collapsible", [True, False])
def test_callouts_are_readable_without_expansion(kind, tag, collapsible):
    root = ET.fromstring(_render_block(
        {"type": kind, "id": "n1", "title": "A < B", "text": "Read & understand."},
        {"collapsible": collapsible},
    ))
    assert root.tag == tag
    assert root.attrib["id"] == "n1"
    assert root.find(".//details") is None
    assert root.find(".//summary") is None
    assert "".join(root.itertext()) == "A < BRead & understand."


@pytest.mark.parametrize("title", [None, "", "   "])
def test_deduplicated_callout_titles_do_not_reappear_as_note(title):
    blocks = [
        {"type": "note", "id": "n1", "title": "2 Method", "text": "First.", "metadata": {"callout_id": "c1"}},
        {"type": "note", "id": "n2", "text": "Second.", "metadata": {"callout_id": "c1"}},
    ]
    if title is not None:
        blocks[1]["title"] = title
    dedupe_callout_titles(blocks)
    html = document_to_html({"sections": [{"blocks": blocks}]})
    assert html.count("2 Method") == 1
    assert "Note" not in html
    assert "<details" not in html
    assert html.count("<aside") == 2


@pytest.mark.parametrize("collapsible,tag", [(True, "details"), (False, "section")])
def test_explicit_details_respect_the_output_profile(collapsible, tag):
    root = ET.fromstring(_render_block(
        {"type": "details", "id": "d1", "title": "More", "text": "Body."},
        {"collapsible": collapsible},
    ))
    assert root.tag == tag
    assert "open" not in root.attrib
    assert "".join(root.itertext()) == "MoreBody."


@pytest.mark.parametrize("source", ["ast", "caption", "title"])
def test_scroll_region_uses_available_caption_without_mutating_the_table(source):
    block = {"type": "table", "id": "t1", "table_ast": {"body": [{"cells": [{"text": "Column"}]}, {"cells": [{"text": "Value"}]}]}}
    caption = 'Values < limits & "units"'
    if source == "ast":
        block["table_ast"]["caption"] = caption
    else:
        block[source] = caption
    original = deepcopy(block)
    root = ET.fromstring(_render_block(block, {}))
    assert block == original
    assert root.attrib == {"class": "table-wrap", "tabindex": "0", "role": "region", "aria-labelledby": "t1-caption"}
    table = root.find("table")
    assert table.attrib["id"] == "t1"
    assert table[0].tag == "caption"
    assert table[0].attrib == {"id": root.attrib["aria-labelledby"]}
    assert "".join(table[0].itertext()) == caption
    assert table.find(".//th").attrib["scope"] == "col"


def test_ast_caption_has_precedence_over_block_title_and_caption():
    root = ET.fromstring(_render_block({
        "type": "table", "title": "Title", "caption": "Legacy caption",
        "table_ast": {"caption": "AST caption", "body": [{"cells": [{"text": "A"}]}]},
    }, {}))
    caption = root.find("table/caption")
    assert root.attrib["aria-labelledby"] == caption.attrib["id"]
    assert "aria-label" not in root.attrib
    assert caption.text == "AST caption"


@pytest.mark.parametrize("caption", [None, "", "   "])
def test_uncaptioned_scroll_region_uses_a_short_generic_label(caption):
    block = {"type": "table", "rows": [["Quantity", "SI unit"], ["Distance", "metre"]], "caption": caption}
    root = ET.fromstring(_render_block(block, {}))
    assert root.attrib["tabindex"] == "0"
    assert root.attrib["role"] == "region"
    assert root.attrib["aria-label"] == "Table 1"
    assert "aria-labelledby" not in root.attrib
    assert root.find("table/caption") is None


def test_scroll_region_does_not_invent_a_caption_for_an_empty_first_cell():
    root = ET.fromstring(_render_block({"type": "table", "rows": [["", "Value"], ["A", "1"]]}, {}))
    assert root.attrib["aria-label"] == "Table 1"
    assert root.find("table/caption") is None


@pytest.mark.parametrize("label,expected", [
    ("Tabela {number}", "Tabela 1"),
    ('Tableau n° {number} < & "', 'Tableau n° 1 < & "'),
    ("Tabela", "Tabela"),
])
@pytest.mark.parametrize("text", ["", "Private cell content"])
def test_uncaptioned_table_uses_a_consumer_supplied_region_label(label, expected, text):
    html = document_to_html(
        {"sections": [{"blocks": [{"type": "table", "id": "empty", "table_ast": {
            "body": [{"cells": [{"text": text}]}],
        }}]}]},
        labels=HtmlLabels(extra={"table_region": label}),
    )
    # The wrapper is XML-compatible even though the full page has HTML void tags.
    fragment = html[html.index('<div class="table-wrap"'):html.index('</table></div>') + len('</table></div>')]
    root = ET.fromstring(fragment)
    assert root.attrib["aria-label"] == expected
    assert "aria-labelledby" not in root.attrib
    assert "<caption" not in html


def test_table_numbers_and_caption_references_follow_document_order():
    def table(**fields):
        return {"type": "table", "rows": [["Header"], ["Value"]], **fields}

    html = document_to_html({"sections": [{
        "blocks": [table(caption="First"), table()],
        "children": [{"blocks": [table(caption="Third"), table()]}],
    }]}, labels=HtmlLabels(extra={"table_region": "Tabela {number}"}))
    # Four table wrappers, including two captioned tables without canonical IDs.
    roots = [ET.fromstring(line) for line in html.splitlines()
             if line.startswith('<div class="table-wrap"')]
    assert len(roots) == 4
    assert roots[0].attrib["aria-labelledby"] == "table-1-caption"
    assert roots[2].attrib["aria-labelledby"] == "table-3-caption"
    for root in (roots[0], roots[2]):
        assert root.find("table/caption").attrib["id"] == root.attrib["aria-labelledby"]
        assert "aria-label" not in root.attrib
    assert roots[1].attrib["aria-label"] == "Tabela 2"
    assert roots[3].attrib["aria-label"] == "Tabela 4"


def test_callout_prose_keeps_inline_math_and_escapes_markup():
    root = ET.fromstring(_render_block({
        "type": "note", "text": "A < B: $x^2$", "metadata": {
            "inline_math": [{"source": "x^2", "speech": "x squared"}],
        },
    }, {"collapsible": True}))
    assert root.tag == "aside"
    assert root.find("p/span").attrib == {"role": "math", "aria-label": "x squared"}
    assert root.find("p").text == "A < B: "


def _ids(html):
    import re
    return re.findall(r'\bid="([^"]+)"', html)


def test_caption_ids_do_not_collide_with_existing_ids():
    html = document_to_html({"sections": [{"blocks": [
        {"type": "paragraph", "id": "t1-caption", "text": "Unrelated paragraph"},
        {"type": "table", "id": "t1", "caption": "Actual caption", "rows": [["Header"], ["Value"]]},
    ]}]})
    fragment = html[html.index('<div class="table-wrap"'):html.index('</table></div>') + len('</table></div>')]
    root = ET.fromstring(fragment)
    caption_id = root.find("table/caption").attrib["id"]
    assert caption_id != "t1-caption"
    assert root.attrib["aria-labelledby"] == caption_id
    ids = _ids(html)
    assert len(ids) == len(set(ids))


def test_a_numbered_caption_id_does_not_collide_with_another_tables_caption_id():
    html = document_to_html({"sections": [{"blocks": [
        {"type": "table", "caption": "First", "rows": [["A"], ["1"]]},
        {"type": "table", "id": "table-1", "caption": "Second", "rows": [["B"], ["2"]]},
    ]}]})
    roots = [ET.fromstring(line) for line in html.splitlines()
             if line.startswith('<div class="table-wrap"')]
    labelled = [root.attrib["aria-labelledby"] for root in roots]
    assert len(set(labelled)) == 2
    for root in roots:
        assert root.find("table/caption").attrib["id"] == root.attrib["aria-labelledby"]
    ids = _ids(html)
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize("kind", ["note", "warning"])
def test_callouts_are_notes_named_by_their_title_not_unnamed_landmarks(kind):
    html = document_to_html({"sections": [{"blocks": [
        {"type": kind, "id": "c1", "title": "Watch out", "text": "First."},
        {"type": kind, "id": "c2", "text": "Second, untitled."},
        {"type": "paragraph", "id": "c1-title", "text": "Taken id."},
    ]}]})
    asides = [ET.fromstring(line) for line in html.splitlines() if line.startswith("<aside")]
    assert len(asides) == 2
    assert all(aside.attrib["role"] == "note" for aside in asides)
    titled, untitled = asides
    title = titled.find("p[@id]")
    assert titled.attrib["aria-labelledby"] == title.attrib["id"] != "c1-title"
    assert "".join(title.itertext()) == "Watch out"
    assert "aria-labelledby" not in untitled.attrib
    ids = _ids(html)
    assert len(ids) == len(set(ids))


def test_block_caption_fallback_is_sanitized_before_export_without_mutating_input():
    from docstruct.canonical import sanitize_canonical_document

    document = {"title": "Doc", "sections": [{"title": "S", "blocks": [{
        "type": "table", "id": "t1", "caption": "Caption a\x02b",
        "table_ast": {"body": [{"cells": [{"text": "Column"}]}, {"cells": [{"text": "Value"}]}]},
    }]}]}
    original = deepcopy(document)
    html = document_to_html(sanitize_canonical_document(document))
    assert "\x02" not in html
    assert ">Caption ab</caption>" in html
    assert document == original
