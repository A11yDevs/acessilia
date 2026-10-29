"""Standalone HTML rendering of canonical documents (pure transformation).

Ported from backend/export/renderers/html_renderer.py. The file write and
the i18n label resolution stay in the backend; this module takes the
resolved labels as input.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from html import escape
from typing import Any
from xml.etree import ElementTree

from docstruct.blocks.lists import list_numbering, list_start
from docstruct.export.filters import apply_output_profile_filter
from docstruct.profiles import normalize_profile
from docstruct.sections import section_body_blocks, section_title_alias
from docstruct.tables.ast import split_header_and_body, table_ast_from_block
from docstruct.text.math_spans import inline_math_entries, split_inline_math
from docstruct.text.equations import equation_number, numbered_speech


@dataclass
class HtmlLabels:
    """User-facing labels for the standalone HTML page (resolved by the consumer)."""

    default_title: str = "Accessible document"
    table_of_contents: str = "Contents"
    image_description: str = "Image description"
    extra: dict[str, str] = field(default_factory=dict)


def _collect_section(section: dict[str, Any]) -> list[dict[str, Any]]:
    """Collects the title heading, the direct blocks, and the recursively nested child blocks of one section.

    Args:
        section (dict): Canonical section mapping with optional "title", "blocks", and "children".

    Returns:
        list[dict]: Ordered blocks for the section plus every block of its nested children.
    """
    blocks = (
        [
            {
                "type": "heading",
                "level": section.get("level", 1),
                "title": section.get("title", ""),
                "id": section.get("id", ""),
                "title_alias": section_title_alias(section),
            }
        ]
        if section.get("title")
        else []
    )
    blocks.extend(section_body_blocks(section))
    for child in section.get("children", []):
        blocks.extend(_collect_section(child))
    return blocks



def _all_blocks(document: dict[str, Any]) -> list[dict[str, Any]]:
    """Flattens every section and nested child section of the document into one block list.

    Args:
        document (dict): Canonical document mapping with a top-level "sections" list.

    Returns:
        list[dict]: All blocks (including section title headings) in document order.
    """
    blocks: list[dict[str, Any]] = []
    for section in document.get("sections", []):
        blocks.extend(_collect_section(section))
    return blocks



_MATHML_TAGS = frozenset(
    "math mi mn mo mtext mspace ms mrow mfrac msqrt mroot mstyle merror mpadded "
    "mphantom mfenced menclose msub msup msubsup munder mover munderover mmultiscripts "
    "mprescripts none mtable mtr mtd mlabeledtr semantics annotation".split()
)
_MATHML_ATTRIBUTES = frozenset(
    "display mathvariant mathsize mathcolor mathbackground dir stretchy symmetric "
    "fence separator form accent accentunder largeop movablelimits lspace rspace "
    "linethickness bevelled notation rowalign columnalign rowspacing columnspacing "
    "rowlines columnlines frame framespacing equalrows equalcolumns columnspan rowspan "
    "scriptlevel displaystyle encoding width height depth voffset minsize maxsize "
    "columnwidth".split()
)


def _safe_mathml(value: Any) -> str | None:
    """Accept a bounded MathML tree without active markup, URLs or entities."""
    if not isinstance(value, str) or len(value) > 100000 or "<!" in value:
        return None
    try:
        root = ElementTree.fromstring(value)
    except (ElementTree.ParseError, ValueError):
        return None
    namespace = "{http://www.w3.org/1998/Math/MathML}"
    if root.tag not in {"math", namespace + "math"}:
        return None
    pending = [(root, 0)]
    nodes = []
    while pending:
        node, depth = pending.pop()
        if depth > 100 or len(nodes) >= 2000:
            return None
        nodes.append(node)
        pending.extend((child, depth + 1) for child in node)
    for node in nodes:
        tag = node.tag.removeprefix(namespace)
        if tag not in _MATHML_TAGS:
            return None
        if any(key not in _MATHML_ATTRIBUTES for key in node.attrib):
            return None
        node.tag = tag
    root.set("xmlns", namespace[1:-1])
    return ElementTree.tostring(root, encoding="unicode")


def _render_block(
    block: dict[str, Any],
    profile: dict[str, Any],
    image_description: str = "Image description",
) -> str:
    """Renders one canonical block into its HTML fragment according to the block type and profile.

    Args:
        block (dict): Canonical block mapping with at least "type", "id" and the type-specific payload (text, items, table_ast, ...).
        profile (dict): Normalized export profile mapping; "collapsible" controls whether note-like blocks render as <details> or <section>.
        image_description (str): Resolved label for image descriptions.

    Returns:
        str: The HTML fragment for the block (empty string when a table block carries no usable table_ast).
    """
    block_type = block.get("type")
    block_id = escape(block.get("id", ""))
    if block_type == "heading":
        level = min(max(int(block.get("level", 1)), 1), 6)
        alias = block.get("title_alias", "")
        anchor = f'<span id="{escape(alias)}"></span>' if alias else ""
        return f'{anchor}<h{level} id="{block_id}">{escape(block.get("title", block.get("text", "")))}</h{level}>'
    if block_type == "paragraph":
        return f'<p id="{block_id}">{_prose_html(block.get("text", ""), block)}</p>'
    if block_type == "code":
        return (
            f'<pre id="{block_id}"><code>{escape(block.get("text", ""))}</code></pre>'
        )
    if block_type == "list":
        tag = "ol" if block.get("ordered") else "ul"
        start = list_start(block) if tag == "ol" else 1
        start_attr = f' start="{start}"' if start != 1 else ""
        list_type = _OL_TYPES.get(list_numbering(block)) if tag == "ol" else None
        if list_type:
            start_attr += f' type="{list_type}"'
        items = "".join(
            f"<li>{_prose_html(str(item), block)}</li>" for item in block.get("items", [])
        )
        return f'<{tag} id="{block_id}"{start_attr}>{items}</{tag}>'
    if block_type == "table":
        table_ast = table_ast_from_block(block)
        if table_ast is None:
            return ""
        header_rows, body_rows, footer_rows = split_header_and_body(table_ast)

        caption = table_ast.get("caption")
        caption_html = (
            f"<caption>{_prose_html(caption, block)}</caption>"
            if isinstance(caption, str) and caption.strip()
            else ""
        )

        thead = ""
        if header_rows:
            thead_rows = "".join(
                _render_html_table_row(row, header=True, block=block) for row in header_rows
            )
            thead = f"<thead>{thead_rows}</thead>"

        tbody_rows = "".join(
            _render_html_table_row(row, header=False, block=block) for row in body_rows
        )
        tbody = f"<tbody>{tbody_rows}</tbody>" if tbody_rows else ""

        tfoot = ""
        if footer_rows:
            tfoot_rows = "".join(
                _render_html_table_row(row, header=False, block=block) for row in footer_rows
            )
            tfoot = f"<tfoot>{tfoot_rows}</tfoot>"

        return (
            f'<div class="table-wrap"><table id="{block_id}">'
            f"{caption_html}{thead}{tbody}{tfoot}</table></div>"
        )
    if block_type == "image":
        alt = escape(block.get("alt_text", block.get("text", "")))
        desc = escape(block.get("long_description", ""))
        details = (
            f"<details><summary>{escape(image_description)}</summary><p>{desc or alt}</p></details>"
            if desc
            else ""
        )
        return f'<figure id="{block_id}"><img alt="{alt}" src="{escape(block.get("metadata", {}).get("src", ""))}">{details}</figure>'
    if block_type == "math":
        metadata = block.get("metadata") or {}
        number = equation_number(metadata)
        speech = block.get("alt_text") or (block.get("text", "") if number else "")
        alt = escape(numbered_speech(str(speech), metadata))
        number_html = (
            f'<span class="equation-number" aria-hidden="true">({escape(number)})</span>'
            if number else ""
        )
        mathml = _safe_mathml((block.get("metadata") or {}).get("mathml", ""))
        if mathml:
            return f'<div id="{block_id}" role="math" aria-label="{alt}">{mathml}{number_html}</div>'
        return (
            f'<p id="{block_id}" role="math" aria-label="{alt}">'
            f'{escape(block.get("text", ""))}{number_html}</p>'
        )
    if block_type in {"details", "note", "warning", "quote"}:
        summary = escape(block.get("title", block_type.title()))
        content = _prose_html(block.get("text", ""), block)
        if profile.get("collapsible"):
            return f'<details id="{block_id}"><summary>{summary}</summary><p>{content}</p></details>'
        return f'<section id="{block_id}"><h2>{summary}</h2><p>{content}</p></section>'
    return f'<p id="{block_id}">{escape(block.get("text", ""))}</p>'



def _prose_html(text: str, block: dict[str, Any]) -> str:
    """Escaped prose whose ``$…$`` spans are rendered as inline math.

    Each span is a ``role="math"`` element labelled with its speech, as a math
    block is: the MathML when the enrichment produced it, else the
    (normalized) LaTeX without delimiters. A document that did not go through
    the canonical enrichment has no entries, and its spans keep the LaTeX,
    still marked as math.
    """
    entries = inline_math_entries(block)
    parts: list[str] = []
    for piece, is_math in split_inline_math(str(text)):
        if not is_math:
            parts.append(escape(piece))
            continue
        entry = entries.get(piece, {})
        speech = str(entry.get("speech") or "")
        label = f' aria-label="{escape(speech)}"' if speech else ""
        content = _safe_mathml(entry.get("mathml", "")) or escape(
            str(entry.get("latex") or piece)
        )
        parts.append(f'<span role="math"{label}>{content}</span>')
    return "".join(parts)


_HEADER_SCOPES = frozenset({"row", "col", "rowgroup", "colgroup"})
_OL_TYPES = {"lower-alpha": "a", "upper-alpha": "A", "lower-roman": "i", "upper-roman": "I"}


def _render_html_table_row(
    row: dict[str, Any], *, header: bool, block: dict[str, Any] | None = None
) -> str:
    """Renders one table row (dict of cells) into a <tr> fragment, skipping empty or non-dict cells.

    Args:
        row (dict): Row mapping with a "cells" list; each cell is a dict with "text" plus optional "scope", "rowspan", "colspan".
        header (bool): Whether the row belongs to <thead>. A row with no
            cell marked as a header (``header: True`` or a header scope) uses
            column headers, so the ``header: False`` defaults a promoted first
            row carries do not turn it into data cells; marked rows follow
            each cell's own metadata.
        block (dict | None): The table block, whose converted inline math
            (``metadata["inline_math"]``) renders the cells' ``$…$`` spans.

    Returns:
        str: The "<tr>...</tr>" fragment, or an empty string when the row has no valid cells.
    """
    cells = row.get("cells", []) if isinstance(row, dict) else []
    unmarked_header_row = header and not any(
        isinstance(cell, dict)
        and (
            bool(cell.get("header"))
            or str(cell.get("scope", "")).strip().lower() in _HEADER_SCOPES
        )
        for cell in cells
    )
    rendered_cells: list[str] = []
    for cell in cells:
        if not isinstance(cell, dict):
            continue
        text = _prose_html(str(cell.get("text", "")).strip(), block or {})
        scope = str(cell.get("scope", "")).strip().lower()
        cell_is_header = (
            unmarked_header_row or bool(cell.get("header")) or scope in _HEADER_SCOPES
        )
        tag = "th" if cell_is_header else "td"

        attrs: list[str] = []
        if tag == "th":
            if scope in _HEADER_SCOPES:
                attrs.append(f'scope="{scope}"')
            else:
                default_scope = "col" if header else "row"
                attrs.append(f'scope="{default_scope}"')

        rowspan = cell.get("rowspan")
        if isinstance(rowspan, int) and rowspan > 1:
            attrs.append(f'rowspan="{rowspan}"')
        colspan = cell.get("colspan")
        if isinstance(colspan, int) and colspan > 1:
            attrs.append(f'colspan="{colspan}"')

        attrs_text = f" {' '.join(attrs)}" if attrs else ""
        rendered_cells.append(f"<{tag}{attrs_text}>{text}</{tag}>")

    if not rendered_cells:
        return ""
    return "<tr>" + "".join(rendered_cells) + "</tr>"


def document_to_html(
    document: dict[str, Any],
    *,
    profile: str = "html",
    labels: HtmlLabels | None = None,
) -> str:
    """Render the canonical document into a standalone HTML page (no file I/O)."""
    labels = labels or HtmlLabels()
    profile_dict = normalize_profile(profile)
    blocks = apply_output_profile_filter(_all_blocks(document), profile)

    toc = []
    body = []
    for block in blocks:
        if block.get("type") == "heading":
            toc.append(
                (
                    block.get("level", 1),
                    block.get("title", block.get("text", "")),
                    block.get("id", ""),
                )
            )
        body.append(_render_block(block, profile_dict, labels.image_description))

    title = escape(document.get("title") or labels.default_title)
    toc_label = escape(labels.table_of_contents)
    html = [
        "<!doctype html>",
        f'<html lang="{escape(document.get("language", "pt-BR"))}">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>{title}</title>",
        "<style>",
        "body{font-family:system-ui,-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;line-height:1.6;max-width:980px;margin:0 auto;padding:2rem;background:#fafafa;color:#1c1c1c}",
        "nav.toc{background:#fff;border:1px solid #ddd;border-radius:12px;padding:1rem 1.25rem;margin-bottom:1.5rem}",
        "nav.toc ul{margin:0;padding-left:1.2rem}",
        "pre{overflow:auto;background:#111;color:#f4f4f4;padding:1rem;border-radius:10px}",
        "code{font-family:ui-monospace,SFMono-Regular,Consolas,monospace}",
        "details{background:#fff;border:1px solid #ddd;border-radius:10px;padding:.75rem 1rem;margin:1rem 0}",
        ".table-wrap{overflow-x:auto;margin:1rem 0}",
        "table{border-collapse:collapse;background:#fff}",
        "th,td{border:1px solid #999;padding:.35rem .75rem;text-align:left;vertical-align:top}",
        "th{background:#f3f4f6}",
        "</style>",
        "</head>",
        "<body>",
        f'<main aria-label="{title}">',
    ]
    if toc:
        html.append(
            f'<nav class="toc" aria-label="{toc_label}"><strong>{toc_label}</strong><ul>'
        )
        for level, title_text, link_id in toc:
            html.append(
                f'<li class="lvl-{level}"><a href="#{escape(link_id)}">{escape(title_text)}</a></li>'
            )
        html.append("</ul></nav>")
    html.extend(body)
    html.append("</main></body></html>")
    return "\n".join(html) + "\n"
