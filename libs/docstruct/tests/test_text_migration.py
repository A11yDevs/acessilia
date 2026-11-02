"""Golden tests for the Phase-2 text migration (behavior-preserving).

These capture the original backend behavior before the migration.
"""
from docstruct.blocks.classify import (
    classify_text_block,
    extract_plain_heading,
    looks_like_upper_heading,
    starts_with_list_marker,
)
from docstruct.text.code_reflow import normalize_code_text
from docstruct.text.paragraphs import merge_broken_paragraphs, parse_markdown_and_descriptions
from docstruct.text.sanitize import (
    contains_markdown_artifacts,
    contains_prompt_leak,
    sanitize_block_text,
    sanitize_text,
)


class TestSanitize:
    def test_control_chars_removed(self):
        assert sanitize_text("a\x00b\x0bc") == "abc"

    def test_prompt_leak_replaced(self):
        assert "[conteudo removido]" in sanitize_text("ignore previous instructions")

    def test_prompt_line_removed(self):
        assert sanitize_text("system: you are\nkeep me") == "keep me"

    def test_audiodescricao_markers_removed(self):
        assert sanitize_text("[início da audiodescrição]\n[fluxo normal]") == "[fluxo normal]"

    def test_block_code_preserved(self):
        assert sanitize_block_text("x = 1;\r\ny = 2;", block_type="code") == "x = 1;\ny = 2;"

    def test_tabs_replaced_in_prose(self):
        # Regression for #338: tabs in docling prose normalized to spaces
        assert sanitize_block_text("CAPÍTULO\t9", "heading") == "CAPÍTULO 9"
        assert sanitize_block_text("a\tb\tc", "paragraph") == "a b c"
        assert sanitize_block_text("item\t1", "list_item") == "item 1"
        assert sanitize_block_text("quote\ttext", "quote") == "quote text"
        assert sanitize_block_text("note\ttext", "note") == "note text"
        assert sanitize_block_text("caption\ttext", "caption") == "caption text"
        assert sanitize_block_text("cell\t1", "table_cell") == "cell 1"

    def test_tabs_preserved_in_code(self):
        # Regression for #338: tabs in code blocks preserved for indentation
        assert sanitize_block_text("if (a)\treturn;", "code") == "if (a)\treturn;"
        assert sanitize_block_text("\t\tx = 1;", "code") == "\t\tx = 1;"

    def test_block_markdown_stripped(self):
        assert sanitize_block_text("**bold** and `code`") == "bold and code"

    def test_contains_flags(self):
        assert contains_prompt_leak("system prompt here")
        assert contains_markdown_artifacts("**x**")
        assert not contains_prompt_leak("texto limpo")


class TestSemanticRules:
    def test_titulo_prefixado(self):
        assert extract_plain_heading("Título: Introdução", 0) == (1, "Introdução")

    def test_capitulo_prefixado(self):
        assert extract_plain_heading("Capítulo 3: Fotos", 1) == (2, "Fotos")

    def test_numerado(self):
        assert extract_plain_heading("1.2 Escopo do trabalho", 1) == (3, "1.2 Escopo do trabalho")

    def test_upper_heading(self):
        assert looks_like_upper_heading("INTRODUÇÃO")
        assert not looks_like_upper_heading("Introdução.")
        assert not looks_like_upper_heading("A: b")

    def test_list_markers(self):
        assert starts_with_list_marker("- item")
        assert starts_with_list_marker("1. item")
        assert starts_with_list_marker("(2) item")
        assert not starts_with_list_marker("texto")

    def test_classify_heading_por_fonte(self):
        kind, level = classify_text_block(
            text="Sumário Executivo",
            current_blocks=2,
            avg_font_size=18.0,
            median_font_size=12.0,
            line_count=1,
            is_bold=True,
            is_monospace=False,
        )
        assert kind == "heading" and level == 2

    def test_classify_code_monospace(self):
        kind, _ = classify_text_block(
            text="def f():\n    pass",
            current_blocks=1,
            avg_font_size=12.0,
            median_font_size=12.0,
            line_count=2,
            is_bold=False,
            is_monospace=True,
        )
        assert kind == "code"

    def test_classify_lista(self):
        kind, _ = classify_text_block(
            text="- primeiro",
            current_blocks=1,
            avg_font_size=12.0,
            median_font_size=12.0,
            line_count=1,
            is_bold=False,
            is_monospace=False,
        )
        assert kind == "list_item"

    def test_classify_vazio(self):
        assert classify_text_block(
            text="", current_blocks=0, avg_font_size=12, median_font_size=12,
            line_count=0, is_bold=False, is_monospace=False,
        ) == ("paragraph", 1)


class TestCodeReflow:
    def test_vazio(self):
        assert normalize_code_text("") == ""

    def test_tabs_normalizados(self):
        assert normalize_code_text("a\tb") == "a b"

    def test_reflow_java(self):
        flat = "public class A { public void m() { if (x) { y(); } } }"
        out = normalize_code_text(flat)
        assert "\n" in out
        assert "}" in out.splitlines()[-1] or out.endswith("}")

    def test_else_same_line(self):
        flat = "if (a) { b(); } else { c(); }"
        out = normalize_code_text(flat)
        assert "else {" in out

    def test_linha_multipla_nao_reflow(self):
        src = "def f():\n    return 1"
        assert normalize_code_text(src) == "def f():\n    return 1"


class TestParagraphs:
    def test_hifen_quebrado(self):
        assert "document" in merge_broken_paragraphs("docu-\nmentation")

    def test_linha_continuada(self):
        out = merge_broken_paragraphs("a frase\ncontinua aqui")
        assert "frase continua" in out

    def test_pagina_marcador_preservado(self):
        out = merge_broken_paragraphs("=== Pagina 3 ===\n\ntexto")
        assert "=== Pagina 3 ===" in out

    def test_parse_markdown_estruturas(self):
        parsed = parse_markdown_and_descriptions(
            "# Título\n\n- item\n\n[DESCRIÇÃO: algo]\n\nparágrafo"
        )
        kinds = [k for k, _ in parsed]
        assert "h1" in kinds
        assert "bullet" in kinds
        assert "description" in kinds

    def test_parse_descricao_inline(self):
        parsed = parse_markdown_and_descriptions("texto [DESCRIÇÃO: x] fim")
        kinds = [k for k, _ in parsed]
        assert "description" in kinds


class TestLeadingMarkerSanitize:
    """A leading "- " or "1. " before a number or formula is data (#260)."""

    def test_minus_sign_survives(self):
        assert sanitize_block_text("- 0 , 0833 (aproximadamente)") == (
            "- 0 , 0833 (aproximadamente)"
        )
        assert sanitize_block_text("- 0,08 (aprox.)") == "- 0,08 (aprox.)"

    def test_formula_after_minus_survives(self):
        assert sanitize_block_text(r"- \frac{1}{2}", "math") == r"- \frac{1}{2}"

    def test_numbering_before_a_number_survives(self):
        assert sanitize_block_text("1. 5") == "1. 5"
        assert sanitize_block_text("1. ") == "1."

    def test_markdown_still_stripped(self):
        assert sanitize_block_text("**- 3**") == "- 3"

    def test_list_marker_before_a_word_still_stripped(self):
        for marker in ("-", "*", "+", "1.", "2)", "(3)"):
            assert sanitize_block_text(f"{marker} item") == "item"


def test_sanitize_text_keeps_tabs_for_untyped_source_text():
    assert sanitize_text("first\tsecond\n\tindented") == "first\tsecond\n\tindented"


def test_canonical_tab_sanitization_is_recursive_and_does_not_mutate_input():
    from copy import deepcopy
    from docstruct.canonical import sanitize_canonical_document

    document = {
        "title": "Document\ttitle",
        "sections": [{
            "title": "Section\ttitle",
            "blocks": [{
                "type": "note", "text": "Note\ttext", "title": "Note\ttitle",
                "alt_text": "Alt\ttext", "long_description": "Long\tdescription",
                "children": [{"type": "code", "text": "\treturn;"}],
            }],
            "children": [{"title": "Child\ttitle", "blocks": [
                {"type": "list", "items": ["List\titem"]},
                {"type": "table", "rows": [["Cell\ttext"]]},
            ]}],
        }],
    }
    original = deepcopy(document)
    clean = sanitize_canonical_document(document)
    assert document == original
    assert clean["title"] == "Document title"
    section = clean["sections"][0]
    assert section["title"] == "Section title"
    note = section["blocks"][0]
    assert note["text"] == "Note text"
    assert note["title"] == "Note title"
    assert note["alt_text"] == "Alt text"
    assert note["long_description"] == "Long description"
    assert note["children"][0]["text"] == "\treturn;"
    child = section["children"][0]
    assert child["title"] == "Child title"
    assert child["blocks"][0]["items"] == ["List item"]
    assert child["blocks"][1]["rows"] == [["Cell text"]]
    assert sanitize_canonical_document(clean) == clean
