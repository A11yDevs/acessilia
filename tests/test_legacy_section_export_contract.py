"""Legacy section titles render once while both anchor identities survive."""
from copy import deepcopy

import fitz
import pytest

from backend.export.renderers.pdf_renderer import render_pdf
from backend.pipeline.canonical_builder import build_canonical_document
from docstruct.export.html import document_to_html
from docstruct.export.pandoc_ast import build_pandoc_ast
from docstruct.export.txt import document_to_txt_lines
from docstruct.sections import section_body_blocks
from docstruct.validation import validate_canonical_document


def _legacy_document(field="text", nested=False):
    document = build_canonical_document("# Heading\n\nBody content.")
    sections = document["sections"]
    if nested:
        child = deepcopy(sections[0])
        child.update(id="child", title="Child heading", level=2)
        child["blocks"] = [{"id": "child-body", "type": "paragraph", "text": "Child body"}]
        sections[0]["children"] = [child]
        sections = [sections[0], child]
    for section in sections:
        section["blocks"].insert(0, {
            "id": f'{section["id"]}-legacy', "type": "heading", "level": section["level"],
            field: section["title"],
        })
    return document, sections


@pytest.mark.parametrize("field", ["text", "title"])
@pytest.mark.parametrize("nested", [False, True])
@pytest.mark.parametrize("same_id", [False, True])
def test_legacy_titles_render_once_and_keep_aliases(field, nested, same_id):
    document, sections = _legacy_document(field, nested)
    if same_id:
        for section in sections:
            section["blocks"][0]["id"] = section["id"]
    before = deepcopy(document)
    assert not validate_canonical_document(document)
    html = document_to_html(document, profile="html")
    lines = document_to_txt_lines(document)
    ast = build_pandoc_ast(document)
    headers = [block for block in ast["blocks"] if block["t"] == "Header"]
    aliases = [block["c"][0][0] for block in ast["blocks"] if block["t"] == "Div"]
    assert len(headers) == len(sections)
    for section in sections:
        title, level = section["title"], section["level"]
        assert html.count(f'>{title}</h{level}>') == 1
        assert html.count(f'id="{section["id"]}"') == 1
        assert html.count(f'id="{section["id"]}-legacy"') == int(not same_id)
        assert lines.count(title) == 1
        assert (section["id"] + "-legacy" in aliases) == (not same_id)
    assert document == before


def test_legacy_title_deduplication_reaches_pdf(tmp_path):
    # DOCX renders on the Toolbox from the Pandoc AST, whose headers are
    # checked above.
    document, _ = _legacy_document()
    pdf = render_pdf(document, tmp_path / "result.pdf", title="Document")
    with fitz.open(pdf) as rendered:
        text = "\n".join(page.get_text() for page in rendered)
    assert text.splitlines().count("Heading") == 2  # one TOC entry + one body heading


@pytest.mark.parametrize("change", ["text", "level", "position"])
def test_distinct_headings_are_preserved(change):
    document, sections = _legacy_document()
    section = sections[0]
    if change == "text":
        section["blocks"][0]["text"] = "Different heading"
    elif change == "level":
        section["blocks"][0]["level"] = 2
    else:
        section["blocks"].reverse()
    assert len(section_body_blocks(section)) == len(section["blocks"])
    assert len([block for block in build_pandoc_ast(document)["blocks"] if block["t"] == "Header"]) == 2
