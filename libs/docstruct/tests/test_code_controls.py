"""C0 removal in code preserves literal syntax, indentation and line breaks."""
from copy import deepcopy
import json

import pytest

from docstruct.canonical import sanitize_canonical_document
from docstruct.export.html import document_to_html
from docstruct.export.markdown import document_to_markdown
from docstruct.export.pandoc_ast import build_pandoc_ast
from docstruct.export.txt import document_to_txt_lines
from docstruct.text.sanitize import sanitize_block_text


FORBIDDEN_C0 = [chr(n) for n in range(32) if n not in (9, 10, 13)]


@pytest.mark.parametrize("control", FORBIDDEN_C0, ids=lambda c: f"U+{ord(c):04X}")
def test_code_removes_forbidden_controls_and_preserves_literal_content(control):
    raw = f"\t# title\r\n  **literal**{control}`code`\r1. item\nSystem: literal\n"
    expected = "\t# title\n  **literal**`code`\n1. item\nSystem: literal\n"
    assert sanitize_block_text(raw, "code") == expected


def test_canonical_code_is_sanitized_recursively_without_mutating_input():
    code = {"type": "code", "id": "c1", "text": "\tprint('a\x02b')\r\n"}
    document = {"sections": [{"blocks": [code, {"type": "note", "children": [code]}], "children": [{"blocks": [code]}]}]}
    original = deepcopy(document)
    clean = sanitize_canonical_document(document)
    assert document == original
    expected = "\tprint('ab')\n"
    section = clean["sections"][0]
    assert section["blocks"][0]["text"] == expected
    assert section["blocks"][1]["children"][0]["text"] == expected
    assert section["children"][0]["blocks"][0]["text"] == expected
    assert sanitize_canonical_document(clean) == clean


@pytest.mark.parametrize("target", ["html", "txt", "markdown", "docx", "pdf_ua"])
def test_clean_code_reaches_each_export_without_controls(target):
    document = sanitize_canonical_document({"sections": [{"blocks": [{
        "type": "code", "id": "code", "text": "\tprint('a" + "".join(FORBIDDEN_C0) + "b')\n",
    }]}]})
    if target == "html":
        output = document_to_html(document)
        assert "\tprint(&#x27;ab&#x27;)\n" in output
    elif target == "txt":
        output = "\n".join(document_to_txt_lines(document))
    elif target == "markdown":
        output = document_to_markdown(document)
    else:
        ast = build_pandoc_ast(document, target_format=target)
        assert ast["blocks"][0]["t"] == "CodeBlock"
        assert ast["blocks"][0]["c"][1] == "\tprint('ab')\n"
        output = json.dumps(ast, ensure_ascii=False)
        assert "\\u0002" not in output
    assert not any(c in output for c in FORBIDDEN_C0)
