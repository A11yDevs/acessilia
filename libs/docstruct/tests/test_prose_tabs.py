"""TAB normalization must not strip already-canonical title content."""
from copy import deepcopy

import pytest
from docstruct.canonical import build_canonical_document, sanitize_canonical_document
from docstruct.export.html import document_to_html
from docstruct.export.pandoc_ast import build_pandoc_ast
from docstruct.export.txt import document_to_txt_lines
from docstruct.text.sanitize import sanitize_block_text


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("1. Introduction", "1. Introduction"),
        ("2) Methods", "2) Methods"),
        ("**Bold** title", "**Bold** title"),
        ("`Code` title", "`Code` title"),
        ("# Heading", "# Heading"),
        ("1.\tIntroduction", "1. Introduction"),
        ("2) \t Methods", "2) Methods"),
        ("**Bold**\t\ttitle", "**Bold** title"),
        ("\tTitle", "Title"),
        ("Title\t", "Title"),
    ],
)
def test_canonical_titles_only_normalize_tabs(title, expected):
    document = {
        "title": title,
        "sections": [{"id": "parent", "title": title, "blocks": [], "children": [
            {"id": "child", "title": title, "blocks": []},
        ]}],
    }
    original = deepcopy(document)

    clean = sanitize_canonical_document(document)

    assert document == original
    assert clean["title"] == expected
    assert clean["sections"][0]["title"] == expected
    assert clean["sections"][0]["children"][0]["title"] == expected
    assert sanitize_canonical_document(clean) == clean
    assert document_to_txt_lines(clean) == [expected, expected]
    assert f"<title>{expected}</title>" in document_to_html(clean)
    inlines = build_pandoc_ast(clean, target_format="docx")["meta"]["title"]["c"]
    text = "".join(node["c"] if node["t"] == "Str" else " " for node in inlines)
    assert text == expected


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("1. Introduction", "1. Introduction"),
        ("2) Methods", "2) Methods"),
        ("**Bold** title", "**Bold** title"),
        ("`Code` title", "`Code` title"),
        ("# Heading", "# Heading"),
        ("1.\tIntroduction", "1. Introduction"),
        ("2) \t Methods", "2) Methods"),
        ("**Bold**\t\ttitle", "**Bold** title"),
        ("\tTitle", "Title"),
        ("Title\t", "Title"),
    ],
)
def test_block_titles_only_normalize_tabs(title, expected):
    document = {
        "title": "Document",
        "sections": [{
            "title": "Section",
            "blocks": [{"type": "heading", "title": title, "text": title}],
        }],
    }

    clean = sanitize_canonical_document(document)

    block = clean["sections"][0]["blocks"][0]
    assert block["title"] == expected
    assert block["text"] == expected


@pytest.mark.parametrize(
    ("heading", "expected"),
    [
        ("1.\tIntroduction", "1. Introduction"),
        ("**Bold**\ttitle", "**Bold** title"),
    ],
)
def test_numbered_heading_keeps_its_number_when_building_the_canonical(heading, expected):
    payload = {
        "pages": [{
            "blocks": [
                {"type": "heading", "level": 1, "text": heading},
                {"type": "paragraph", "text": "Body."},
            ],
        }],
    }

    document = build_canonical_document(payload, title="doc")

    assert document["title"] == expected
    assert document["sections"][0]["title"] == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("a\t\tb", "a b"),
        ("a \t b", "a b"),
        ("a \t \t b", "a b"),
        ("a \t b\nc\t\td", "a b\nc d"),
        ("a  b", "a  b"),
    ],
)
def test_prose_collapses_tab_runs_without_changing_other_spacing(text, expected):
    assert sanitize_block_text(text, block_type="paragraph") == expected


def test_code_preserves_mixed_spaces_and_tab_runs():
    code = "\t \tfirst\n\t\tsecond\n"
    assert sanitize_block_text(code, block_type="code") == code
