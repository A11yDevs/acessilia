"""Pandoc AST builder for canonical documents.

Ported from backend/pipeline/pandoc_ast_builder.py. Pure: deterministic
document dict -> Pandoc JSON AST (in-memory dict), no I/O.
"""
from __future__ import annotations

import re
from typing import Any
from docstruct.blocks.lists import list_start
from docstruct.sections import section_body_blocks, section_title_alias

from docstruct.tables.ast import effective_section_width, row_header_column_count
from docstruct.tables.ast import split_header_and_body
from docstruct.tables.ast import table_ast_from_block
from docstruct.text.math_spans import inline_math_entries
from docstruct.text.math_spans import split_inline_math


#: Control sequences that read files, execute programs or change TeX's
#: internals. Math text comes from OCR and vision models, and the PDF/UA
#: renderer compiles it with LaTeX: beyond an undefined control sequence
#: losing the whole document (``\chemfig`` from a misclassified chemical
#: structure, for instance), ``\write18`` and friends have no business in a
#: compilation. This list is defense in depth against the common primitives,
#: not a sandbox — the boundary is the Toolbox's own LaTeX configuration
#: (no shell escape, restricted file access) plus the degrade-and-retry of
#: the PDF/UA export. A math block carrying one degrades to plain text, the
#: same representation the renderers already show for an unverbalized
#: formula. Names match whole macros only, so ``\longleftarrow`` is kept.
_LATEX_UNSAFE_MACROS = frozenset(
    {
        "catcode",
        "csname",
        "directlua",
        "documentclass",
        "import",
        "include",
        "includegraphics",
        "input",
        "inputiffileexists",
        "lstinputlisting",
        "luaexec",
        "openin",
        "openout",
        "read",
        "readline",
        "special",
        "usepackage",
        "verbatiminput",
        "write",
    }
)

# ``@`` covers the \makeatletter forms: \@@input is the file-reading
# primitive behind \input.
_LATEX_MACRO_RE = re.compile(r"\\([a-zA-Z@]+)")

#: Class of the span that carries a formula's spoken form to the PDF/UA
#: renderer, which writes it as the Formula element's alternate text.
FORMULA_ALT_CLASS = "accessilia-formula"


def _has_unsafe_latex_macro(latex: str) -> bool:
    """Whether the LaTeX carries a macro the renderers must not compile."""
    return any(
        name.lstrip("@").lower() in _LATEX_UNSAFE_MACROS
        for name in _LATEX_MACRO_RE.findall(latex)
    )


def build_pandoc_ast(document: dict[str, Any]) -> dict[str, Any]:
    blocks = []
    for section in document.get("sections", []):
        blocks.extend(_section_to_blocks(section))
    return {
        "pandoc-api-version": [1, 23, 1],
        "meta": {
            "title": {
                "t": "MetaInlines",
                "c": _meta_inlines(document.get("title", "")),
            },
            "lang": {"t": "MetaString", "c": document.get("language", "pt-BR")},
            "verbosity": {
                "t": "MetaString",
                "c": document.get("verbosity", "detailed"),
            },
        },
        "blocks": blocks,
        "source_document": document,
    }


def _section_to_blocks(section: dict[str, Any]) -> list[dict[str, Any]]:
    # An untitled section (the text before the first heading) gets no Header:
    # an empty one is tagged as an empty H1, as the HTML and text exports skip it.
    blocks = (
        [
            {
                "t": "Header",
                "c": [
                    section.get("level", 1),
                    [section.get("id", ""), [], []],
                    _meta_inlines(section.get("title", "")),
                ],
            }
        ]
        if section.get("title")
        else []
    )
    alias = section_title_alias(section)
    if alias:
        blocks.insert(0, {"t": "Div", "c": [[alias, [], []], []]})
    for block in section_body_blocks(section):
        blocks.extend(_block_to_ast(block))
    for child in section.get("children", []):
        blocks.extend(_section_to_blocks(child))
    return blocks


def _block_to_ast(block: dict[str, Any]) -> list[dict[str, Any]]:
    block_type = block.get("type")
    if block_type == "heading":
        return [
            {
                "t": "Header",
                "c": [
                    block.get("level", 1),
                    [block.get("id", ""), [], []],
                    _meta_inlines(block.get("text", "")),
                ],
            }
        ]
    if block_type == "paragraph":
        return [{"t": "Para", "c": _prose_inlines(block.get("text", ""), block)}]
    if block_type == "code":
        return [
            {
                "t": "CodeBlock",
                "c": [
                    [block.get("id", ""), [block.get("language", "")], []],
                    block.get("text", ""),
                ],
            }
        ]
    if block_type == "list":
        items = [
            [{"t": "Para", "c": _prose_inlines(str(item), block)}]
            for item in block.get("items", [])
        ]
        if block.get("ordered"):
            attributes = [list_start(block), {"t": "Decimal"}, {"t": "Period"}]
            return [{"t": "OrderedList", "c": [attributes, items]}]
        return [{"t": "BulletList", "c": items}]
    if block_type == "table":
        table_ast = table_ast_from_block(block)
        if table_ast is None:
            return []
        return [_table_to_pandoc_ast(table_ast, block)]
    if block_type == "image":
        return [
            {
                "t": "Para",
                "c": _meta_inlines(block.get("alt_text", block.get("text", ""))),
            }
        ]
    if block_type == "math":
        latex = str(block.get("text", ""))
        if _has_unsafe_latex_macro(latex):
            return [{"t": "Para", "c": _meta_inlines(latex)}]
        # A math block is a formula of its own, so it is display math. This
        # reaches every Pandoc writer: DOCX typesets it as a display equation
        # (oMathPara) where it used to be inline. (The HTML export does not go
        # through this AST.)
        math = {"t": "Math", "c": [{"t": "DisplayMath"}, latex]}
        alt_text = str(block.get("alt_text") or "").strip()
        if alt_text:
            # The PDF/UA renderer gives a formula in this span its spoken form
            # as the Formula element's alternate text, instead of the LaTeX
            # source a screen reader would otherwise announce
            # (acessilia-toolbox docs/pdf-ua-export.md, "Formula alternate
            # text"). Other writers ignore the span and render its content;
            # DOCX keeps no alternate text for equations.
            math = {
                "t": "Span",
                "c": [["", [FORMULA_ALT_CLASS], [["alt", alt_text]]], [math]],
            }
        return [{"t": "Para", "c": [math]}]
    if block_type in {"quote", "details", "note", "warning"}:
        return [
            {
                "t": "BlockQuote",
                "c": [{"t": "Para", "c": _prose_inlines(block.get("text", ""), block)}],
            }
        ]
    return [{"t": "Para", "c": _meta_inlines(block.get("text", ""))}]


def _meta_inlines(text: str) -> list[dict[str, Any]]:
    inlines: list[dict[str, Any]] = []
    for chunk in str(text).split(" "):
        if not chunk:
            continue
        if inlines:
            inlines.append({"t": "Space"})
        inlines.append({"t": "Str", "c": chunk})
    return inlines


def _prose_inlines(text: str, block: dict[str, Any]) -> list[dict[str, Any]]:
    """Inlines of a prose text whose ``$…$`` spans become ``InlineMath``.

    A span the canonical enrichment converted takes its normalized LaTeX and,
    with a spoken form, the same alt span as display math, so the PDF/UA
    Formula element is announced by its speech. One carrying an unsafe macro
    stays text, as a math block does.
    """
    entries = inline_math_entries(block)
    inlines: list[dict[str, Any]] = []
    for piece, is_math in split_inline_math(str(text)):
        if not is_math:
            if piece[:1].isspace() and inlines and inlines[-1] != _SPACE:
                inlines.append({"t": "Space"})
            inlines.extend(_meta_inlines(piece))
            if piece[-1:].isspace() and inlines and inlines[-1] != _SPACE:
                inlines.append({"t": "Space"})
            continue
        entry = entries.get(piece, {})
        latex = str(entry.get("latex") or piece)
        if _has_unsafe_latex_macro(latex):
            inlines.extend(_meta_inlines(latex))
            continue
        math: dict[str, Any] = {"t": "Math", "c": [{"t": "InlineMath"}, latex]}
        speech = str(entry.get("speech") or "").strip()
        if speech:
            math = {
                "t": "Span",
                "c": [["", [FORMULA_ALT_CLASS], [["alt", speech]]], [math]],
            }
        inlines.append(math)
    if inlines and inlines[-1] == _SPACE:
        inlines.pop()
    return inlines


_SPACE = {"t": "Space"}


def degrade_math_to_text(document_ast: dict[str, Any]) -> dict[str, Any]:
    """A copy of the Pandoc AST whose Math inlines carry the formula as text.

    The Toolbox compiles the PDF/UA AST with LaTeX, and math its compiler
    rejects (a macro the template does not load, e.g. ``\\chemfig`` from a
    chemical structure a vision model classified as a formula) fails the
    whole document. The fallback exports the formula source as literal text
    — the same representation the HTML and TXT renderers already show — so
    one block cannot lose the PDF. The walk covers the whole payload (a
    ``Math`` inside a quote, a ``Div`` or a table cell degrades too), and the
    input AST is left untouched. With no ``Math`` inline the copy equals the
    input, which callers use to skip a pointless retry.
    """
    return {
        **document_ast,
        "blocks": [
            _degrade_node(block) for block in document_ast.get("blocks", [])
        ],
    }


def _degrade_node(node: Any) -> Any:
    """Rebuild ``node`` with every ``Math`` inline replaced by its text.

    Lists and dicts come back with the same shape: a ``Math`` inline expands
    into the text inlines that replace it in place, everything else is
    walked through ``c`` and rebuilt. A formula span (``FORMULA_ALT_CLASS``)
    is unwrapped too: once its formula is text there is no Formula element
    for the alternate text, and an ``alt`` left on plain text would be
    behaviour nobody asked for.
    """
    if isinstance(node, list):
        rebuilt: list[Any] = []
        for item in node:
            if isinstance(item, dict) and item.get("t") == "Math":
                latex = ""
                if isinstance(item.get("c"), list) and len(item["c"]) > 1:
                    latex = str(item["c"][1])
                rebuilt.extend(_meta_inlines(latex))
            elif _is_formula_span(item):
                rebuilt.extend(_degrade_node(item["c"][1]))
            else:
                rebuilt.append(_degrade_node(item))
        return rebuilt
    if isinstance(node, dict) and "c" in node:
        return {**node, "c": _degrade_node(node["c"])}
    return node


def _is_formula_span(node: Any) -> bool:
    if not isinstance(node, dict) or node.get("t") != "Span":
        return False
    content = node.get("c")
    if not (isinstance(content, list) and len(content) == 2 and isinstance(content[0], list)):
        return False
    attributes = content[0]
    return len(attributes) > 1 and FORMULA_ALT_CLASS in (attributes[1] or [])


def _table_to_pandoc_ast(
    table_ast: dict[str, Any], block: dict[str, Any] | None = None
) -> dict[str, Any]:
    """A Pandoc ``Table``; ``block``'s converted inline math renders the ``$…$``
    of the caption and cells as ``InlineMath`` (#260)."""
    block = block or {}
    header_rows, body_rows, footer_rows = split_header_and_body(table_ast)
    row_head_columns = row_header_column_count(body_rows)

    column_count = max(
        effective_section_width(header_rows),
        effective_section_width(body_rows),
        effective_section_width(footer_rows),
        1,
    )
    colspecs = [
        [{"t": "AlignDefault"}, {"t": "ColWidth", "c": 1.0 / max(column_count, 1)}]
        for _ in range(column_count)
    ]

    caption_text = table_ast.get("caption")
    short_caption = (
        _prose_inlines(caption_text, block)
        if isinstance(caption_text, str) and caption_text.strip()
        else None
    )
    caption = [short_caption, []]

    head = [["", [], []], [_pandoc_row(row, header=True, block=block) for row in header_rows]]
    bodies = [
        [
            ["", [], []],
            row_head_columns,
            [],
            [_pandoc_row(row, header=False, block=block) for row in body_rows],
        ]
    ]
    foot = [["", [], []], [_pandoc_row(row, header=False, block=block) for row in footer_rows]]

    return {
        "t": "Table",
        "c": [
            ["", [], []],
            caption,
            colspecs,
            head,
            bodies,
            foot,
        ],
    }


def _pandoc_row(row: dict[str, Any], *, header: bool, block: dict[str, Any]) -> list[Any]:
    cells = row.get("cells", []) if isinstance(row, dict) else []
    return [
        ["", [], []],
        [
            _pandoc_cell(cell, header=header or _cell_is_header(cell), block=block)
            for cell in cells
            if isinstance(cell, dict)
        ],
    ]


def _cell_is_header(cell: dict[str, Any]) -> bool:
    scope = str(cell.get("scope", "")).strip().lower()
    return bool(cell.get("header")) or scope in {
        "row",
        "rowgroup",
        "col",
        "colgroup",
    }


def _pandoc_cell(cell: dict[str, Any], *, header: bool, block: dict[str, Any]) -> list[Any]:
    text = str(cell.get("text", "")).strip()
    rowspan = cell.get("rowspan") if isinstance(cell.get("rowspan"), int) else 1
    colspan = cell.get("colspan") if isinstance(cell.get("colspan"), int) else 1

    scope = str(cell.get("scope", "")).strip().lower()
    if scope in {"row", "rowgroup"}:
        alignment = {"t": "AlignRight"}
    elif scope in {"col", "colgroup"}:
        alignment = {"t": "AlignLeft"}
    else:
        alignment = {"t": "AlignDefault"}

    block_kind = "Plain" if header else "Para"
    return [
        ["", [], []],
        alignment,
        max(1, int(rowspan)),
        max(1, int(colspan)),
        [{"t": block_kind, "c": _prose_inlines(text, block)}],
    ]
