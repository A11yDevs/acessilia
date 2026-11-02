from docstruct.export.markdown import bare_latex, document_to_markdown, render_table


def _doc(*blocks, title="", section_title="", children=()):
    return {
        "title": title,
        "sections": [
            {"level": 1, "title": section_title, "blocks": list(blocks), "children": list(children)}
        ],
    }


def test_blocks_render_in_reading_order():
    doc = _doc(
        {"type": "paragraph", "text": " Intro "},
        {"type": "math", "text": "$$ E =  mc^2 $$"},
        {"type": "code", "text": "x = 1", "language": "python"},
        {"type": "list", "items": ["a", " ", "b"]},
        {"type": "image", "text": "ignored"},
    )
    assert document_to_markdown(doc) == (
        "Intro\n\n$$\nE = mc^2\n$$\n\n```python\nx = 1\n```\n\n- a\n- b\n"
    )


def test_title_not_repeated_when_it_is_the_first_section():
    doc = _doc(
        {"type": "heading", "level": 1, "text": "Results"},
        {"type": "paragraph", "text": "Body"},
        title="Results",
        section_title="Results",
    )
    assert document_to_markdown(doc) == "# Results\n\nBody\n"


def test_title_emitted_when_distinct_and_children_follow():
    child = {"level": 2, "title": "Method", "blocks": [{"type": "paragraph", "text": "M"}]}
    doc = _doc({"type": "paragraph", "text": "P"}, title="Paper", children=[child])
    assert document_to_markdown(doc) == "# Paper\n\nP\n\n## Method\n\nM\n"


def test_provider_html_table_kept_verbatim():
    assert render_table({"html": " <table><tr><td>1</td></tr></table> "}) == (
        "<table><tr><td>1</td></tr></table>"
    )


def test_table_ast_spans_and_header_scopes():
    ast = {
        "caption": "A & B",
        "header": [{"cells": [{"text": "Mês"}, {"text": "Valor", "colspan": 2}]}],
        "body": [{"cells": [{"text": "Jan", "scope": "row"}, {"text": "<1>", "rowspan": 2}]}],
    }
    assert render_table({"table_ast": ast}) == (
        "<table><caption>A &amp; B</caption>"
        '<thead><tr><th scope="col">Mês</th><th colspan="2" scope="col">Valor</th></tr></thead>'
        '<tbody><tr><th scope="row">Jan</th><td rowspan="2">&lt;1&gt;</td></tr></tbody></table>'
    )


def test_bare_latex_strips_one_delimiter_pair_only():
    assert bare_latex(r"\( a \)") == "a"
    assert bare_latex(r"\[ \alpha \]") == r"\alpha"
    assert bare_latex("$x$") == "x"
    assert bare_latex("$ $") == ""
    # Unlike normalize_latex, the expression is not rewritten.
    assert bare_latex("α ^ { 2 }") == "α ^ { 2 }"
