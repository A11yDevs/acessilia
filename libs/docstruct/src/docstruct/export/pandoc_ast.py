"""Pandoc AST builder for canonical documents.

Ported from backend/pipeline/pandoc_ast_builder.py. Pure: deterministic
document dict -> Pandoc JSON AST (in-memory dict), no I/O.
"""
from __future__ import annotations

import re
from collections.abc import Collection
from typing import Any

from docstruct.blocks.lists import list_numbering, list_start
from docstruct.export.walk import SectionContext, Visitor, walk
from docstruct.tables.ast import (
    effective_section_width,
    row_header_column_count,
    split_header_and_body,
    table_ast_from_block,
)
from docstruct.text.equations import (
    equation_number,
    numbered_latex,
    numbered_speech,
    split_equation_number,
)
from docstruct.text.math_spans import inline_math_entries, split_inline_math

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


def build_pandoc_ast(document: dict[str, Any], *, target_format: str = "latex") -> dict[str, Any]:
    """Build math tags for LaTeX, or portable equation labels for DOCX."""
    blocks = _document_blocks(document, target_format)
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


def _section_to_blocks(section: dict[str, Any], *, target_format: str = "latex") -> list[dict[str, Any]]:
    """Compatibility entry point for one section, including its children."""
    return _document_blocks({"sections": [section]}, target_format)


class _MathStatusTracker:
    """Tracks emitted Math inlines and whether each carried converted MathML."""

    def __init__(self) -> None:
        self.total = 0
        self.with_mathml = 0
        self.without_mathml: list[int] = []

    def record(self, has_mathml: bool) -> None:
        index = self.total
        self.total += 1
        if has_mathml:
            self.with_mathml += 1
        else:
            self.without_mathml.append(index)


def _document_blocks(
    document: dict[str, Any],
    target_format: str,
    *,
    tracker: _MathStatusTracker | None = None,
) -> list[dict[str, Any]]:
    return [block for group in walk(
        document,
        _visitor(target_format, tracker=tracker),
        select=lambda block, ctx: not ctx.is_legacy_title,
    ) for block in group]


def _section_title(ctx: SectionContext) -> list[dict[str, Any]]:
    section = ctx.data
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
    alias = ctx.title_alias
    if alias:
        blocks.insert(0, {"t": "Div", "c": [[alias, [], []], []]})
    return blocks


def _visitor(
    target_format: str, *, tracker: _MathStatusTracker | None = None
) -> Visitor[list[dict[str, Any]]]:
    return Visitor(
        default=lambda block, ctx: _text(block),
        heading=lambda block, ctx: _heading(block),
        paragraph=lambda block, ctx: _paragraph(block, tracker=tracker),
        list=lambda block, ctx: _list(block, tracker=tracker),
        table=lambda block, ctx: _table(block, tracker=tracker),
        image=lambda block, ctx: _image(block),
        code=lambda block, ctx: _code(block),
        math=lambda block, ctx: _math(block, target_format, tracker=tracker),
        quote=lambda block, ctx: _quote(block, tracker=tracker),
        details=lambda block, ctx: _quote(block, tracker=tracker),
        note=lambda block, ctx: _quote(block, tracker=tracker),
        warning=lambda block, ctx: _quote(block, tracker=tracker),
        enter_section=_section_title,
    )


def _block_to_ast(block: dict[str, Any], *, target_format: str = "latex") -> list[dict[str, Any]]:
    """Render one block using the document visitor, without section selection."""
    return [item for group in walk(
        {"sections": [{"blocks": [block]}]}, _visitor(target_format),
    ) for item in group]


def _heading(block: dict[str, Any]) -> list[dict[str, Any]]:
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


def _paragraph(
    block: dict[str, Any], *, tracker: _MathStatusTracker | None = None
) -> list[dict[str, Any]]:
    return [{"t": "Para", "c": _prose_inlines(block.get("text", ""), block, tracker=tracker)}]


def _code(block: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "t": "CodeBlock",
            "c": [
                [block.get("id", ""), [block.get("language", "")], []],
                block.get("text", ""),
            ],
        }
    ]


def _list(
    block: dict[str, Any], *, tracker: _MathStatusTracker | None = None
) -> list[dict[str, Any]]:
    items = [
        [{"t": "Para", "c": _prose_inlines(str(item), block, tracker=tracker)}]
        for item in block.get("items", [])
    ]
    if block.get("ordered"):
        style = _ORDERED_LIST_STYLES[list_numbering(block)]
        attributes = [list_start(block), {"t": style}, {"t": "Period"}]
        return [{"t": "OrderedList", "c": [attributes, items]}]
    return [{"t": "BulletList", "c": items}]


def _table(
    block: dict[str, Any], *, tracker: _MathStatusTracker | None = None
) -> list[dict[str, Any]]:
    table_ast = table_ast_from_block(block)
    if table_ast is None:
        return []
    return [_table_to_pandoc_ast(table_ast, block, tracker=tracker)]


def _image(block: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "t": "Para",
            "c": _meta_inlines(block.get("alt_text", block.get("text", ""))),
        }
    ]


def _math(
    block: dict[str, Any],
    target_format: str,
    *,
    tracker: _MathStatusTracker | None = None,
) -> list[dict[str, Any]]:
    metadata = block.get("metadata") or {}
    latex = numbered_latex(str(block.get("text", "")), metadata, use_tag=target_format != "docx")
    if _has_unsafe_latex_macro(latex):
        return [{"t": "Para", "c": _meta_inlines(_math_as_text(latex))}]
    if tracker is not None:
        tracker.record(bool(metadata.get("mathml")))
    # A math block is a formula of its own, so it is display math. This
    # reaches every Pandoc writer: DOCX typesets it as a display equation
    # (oMathPara) where it used to be inline. (The HTML export does not go
    # through this AST.)
    math: dict[str, Any] = {"t": "Math", "c": [{"t": "DisplayMath"}, latex]}
    speech = block.get("alt_text") or (block.get("text", "") if equation_number(metadata) else "")
    alt_text = numbered_speech(str(speech).strip(), metadata)
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


def _quote(
    block: dict[str, Any], *, tracker: _MathStatusTracker | None = None
) -> list[dict[str, Any]]:
    return [
        {
            "t": "BlockQuote",
            "c": [{"t": "Para", "c": _prose_inlines(block.get("text", ""), block, tracker=tracker)}],
        }
    ]


def _text(block: dict[str, Any]) -> list[dict[str, Any]]:
    # Retain the TypeError for unhashable kinds from the former set dispatch.
    hash(block.get("type"))
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


def _prose_inlines(
    text: str,
    block: dict[str, Any],
    *,
    tracker: _MathStatusTracker | None = None,
) -> list[dict[str, Any]]:
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
        if tracker is not None:
            tracker.record(bool(entry.get("mathml")))
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
_ORDERED_LIST_STYLES = {
    "decimal": "Decimal",
    "lower-alpha": "LowerAlpha",
    "upper-alpha": "UpperAlpha",
    "lower-roman": "LowerRoman",
    "upper-roman": "UpperRoman",
}


def count_math_nodes(document_ast: dict[str, Any]) -> int:
    """Count every ``Math`` inline in ``document_ast`` in pre-order walk order."""
    return _count_math_nodes(document_ast.get("blocks", []))


def _count_math_nodes(node: Any) -> int:
    if isinstance(node, list):
        return sum(_count_math_nodes(item) for item in node)
    if isinstance(node, dict):
        if node.get("t") == "Math":
            return 1
        if "c" in node:
            return _count_math_nodes(node["c"])
    return 0


def unconverted_math_indices(
    document_ast: dict[str, Any], *, target_format: str
) -> frozenset[int]:
    """0-based ``Math`` indices whose source formula lacks converted MathML.

    Precondition: ``document_ast`` must have been built by
    :func:`build_pandoc_ast` with the same ``target_format``; the mapping comes
    from re-walking ``document_ast["source_document"]``, and a mismatch is
    caught only indirectly if the resulting ``Math`` count differs.

    The returned set is only a cheap ordering hint, never proof of rejection: a
    formula can also lack MathML because it was never enriched (for example an
    inline span without ``metadata["inline_math"]``) or because
    ``math.convert`` failed transiently. When no formula carries MathML (or
    every formula does), returns an empty set; callers should also ignore the
    hint when most of the document lacks MathML, where probing the whole
    unconverted set first would spend an extra render before bisecting (#258).
    """
    source = document_ast.get("source_document")
    if not isinstance(source, dict):
        return frozenset()
    tracker = _MathStatusTracker()
    _document_blocks(source, target_format, tracker=tracker)
    if tracker.total != count_math_nodes(document_ast):
        return frozenset()
    if tracker.with_mathml == 0 or not tracker.without_mathml:
        return frozenset()
    return frozenset(tracker.without_mathml)


def degrade_math_to_text(
    document_ast: dict[str, Any], *, indices: Collection[int] | None = None
) -> dict[str, Any]:
    """A copy of the Pandoc AST with selected (or all) ``Math`` inlines as text.

    The Toolbox compiles the PDF/UA AST with LaTeX, and math its compiler
    rejects (a macro the template does not load, e.g. ``\\chemfig`` from a
    chemical structure a vision model classified as a formula) fails the
    whole document. The fallback exports the failing formula source as literal
    text — the same representation the HTML and TXT renderers already show — so
    one block cannot lose the PDF.

    When ``indices`` is ``None`` (the default), every ``Math`` inline is
    degraded. When ``indices`` is given, only the 0-based ``Math`` inlines at
    those pre-order positions are degraded; all other ``Math`` inlines and
    their ``FORMULA_ALT_CLASS`` spans survive untouched (#258). The walk covers
    the whole payload (a ``Math`` inside a quote, a ``Div`` or a table cell
    degrades too), and the input AST is left untouched. With no ``Math`` inline
    degraded, the copy equals the input.
    """
    target = None if indices is None else frozenset(indices)
    cursor = [0]
    return {
        **document_ast,
        "blocks": [
            _degrade_node(block, target, cursor) for block in document_ast.get("blocks", [])
        ],
    }


def _contains_math(node: Any) -> bool:
    if isinstance(node, list):
        return any(_contains_math(item) for item in node)
    if isinstance(node, dict):
        if node.get("t") == "Math":
            return True
        if "c" in node:
            return _contains_math(node["c"])
    return False


def _degrade_node(
    node: Any, target: frozenset[int] | None = None, cursor: list[int] | None = None
) -> Any:
    """Rebuild ``node`` with targeted ``Math`` inlines replaced by their text.

    Lists and dicts come back with the same shape: a degraded ``Math`` inline
    expands into the text inlines that replace it in place, everything else is
    walked through ``c`` and rebuilt. A formula span (``FORMULA_ALT_CLASS``)
    is unwrapped when its formula is degraded — once its formula is text there
    is no Formula element for the alternate text — and preserved when its
    ``Math`` inline survives.
    """
    if cursor is None:
        cursor = [0]
    if isinstance(node, list):
        rebuilt: list[Any] = []
        for item in node:
            if isinstance(item, dict) and item.get("t") == "Math":
                index = cursor[0]
                cursor[0] += 1
                if target is None or index in target:
                    latex = ""
                    if isinstance(item.get("c"), list) and len(item["c"]) > 1:
                        latex = str(item["c"][1])
                    rebuilt.extend(_meta_inlines(_math_as_text(latex)))
                else:
                    rebuilt.append(item)
            elif _is_formula_span(item):
                children = _degrade_node(item["c"][1], target, cursor)
                if _contains_math(children):
                    rebuilt.append({**item, "c": [item["c"][0], children]})
                else:
                    rebuilt.extend(children)
            else:
                rebuilt.append(_degrade_node(item, target, cursor))
        return rebuilt
    if isinstance(node, dict) and "c" in node:
        return {**node, "c": _degrade_node(node["c"], target, cursor)}
    return node


def _math_as_text(latex: str) -> str:
    """A formula shown as text: its equation label as the reader sees it, ``(1)``.

    ``\\tag{1}`` (or the DOCX ``\\qquad\\text{(1)}``) is a command only the math
    renderer reads; left in text it would be read out as a backslash and a word.
    """
    expression, number = split_equation_number(latex)
    return f"{expression} ({number})" if number else latex


def _is_formula_span(node: Any) -> bool:
    if not isinstance(node, dict) or node.get("t") != "Span":
        return False
    content = node.get("c")
    if not (isinstance(content, list) and len(content) == 2 and isinstance(content[0], list)):
        return False
    attributes = content[0]
    return len(attributes) > 1 and FORMULA_ALT_CLASS in (attributes[1] or [])


def _table_to_pandoc_ast(
    table_ast: dict[str, Any],
    block: dict[str, Any] | None = None,
    *,
    tracker: _MathStatusTracker | None = None,
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
        _prose_inlines(caption_text, block, tracker=tracker)
        if isinstance(caption_text, str) and caption_text.strip()
        else None
    )
    caption = [short_caption, []]

    head = [
        ["", [], []],
        [_pandoc_row(row, header=True, block=block, tracker=tracker) for row in header_rows],
    ]
    bodies = [
        [
            ["", [], []],
            row_head_columns,
            [],
            [_pandoc_row(row, header=False, block=block, tracker=tracker) for row in body_rows],
        ]
    ]
    foot = [
        ["", [], []],
        [_pandoc_row(row, header=False, block=block, tracker=tracker) for row in footer_rows],
    ]

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


def _pandoc_row(
    row: dict[str, Any],
    *,
    header: bool,
    block: dict[str, Any],
    tracker: _MathStatusTracker | None = None,
) -> list[Any]:
    cells = row.get("cells", []) if isinstance(row, dict) else []
    return [
        ["", [], []],
        [
            _pandoc_cell(
                cell,
                header=header or _cell_is_header(cell),
                block=block,
                tracker=tracker,
            )
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


def _pandoc_cell(
    cell: dict[str, Any],
    *,
    header: bool,
    block: dict[str, Any],
    tracker: _MathStatusTracker | None = None,
) -> list[Any]:
    text = str(cell.get("text", "")).strip()
    rowspan_value = cell.get("rowspan")
    colspan_value = cell.get("colspan")
    rowspan = rowspan_value if isinstance(rowspan_value, int) else 1
    colspan = colspan_value if isinstance(colspan_value, int) else 1

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
        [{"t": block_kind, "c": _prose_inlines(text, block, tracker=tracker)}],
    ]
