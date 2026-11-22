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
from docstruct.export.walk import BlockContext, SectionContext, Visitor, walk
from docstruct.profiles import normalize_profile
from docstruct.tables.ast import split_header_and_body, table_ast_from_block
from docstruct.text.equations import equation_number, numbered_speech
from docstruct.text.math_spans import inline_math_entries, split_inline_math


@dataclass
class HtmlLabels:
    """User-facing labels for the standalone HTML page (resolved by the consumer).

    ``extra["table_region"]`` names uncaptioned table regions; the optional
    ``{number}`` placeholder is the table's one-based position in the document.
    """

    default_title: str = "Accessible document"
    table_of_contents: str = "Contents"
    image_description: str = "Image description"
    extra: dict[str, str] = field(default_factory=dict)


def _collect_section(section: dict[str, Any]) -> list[dict[str, Any]]:
    """Compatibility entry point for one section, including its children."""
    return _all_blocks({"sections": [section]})


def _section_title(ctx: SectionContext) -> dict[str, Any] | None:
    section = ctx.data
    return (
        {
            "type": "heading",
            "level": section.get("level", 1),
            "title": section.get("title", ""),
            "id": section.get("id", ""),
            "title_alias": ctx.title_alias,
        }
        if section.get("title")
        else None
    )



def _all_blocks(document: dict[str, Any]) -> list[dict[str, Any]]:
    """Flattens every section and nested child section of the document into one block list.

    Args:
        document (dict): Canonical document mapping with a top-level "sections" list.

    Returns:
        list[dict]: All blocks (including section title headings) in document order.
    """
    # Keep collection before the existing global profile filter: it rewrites
    # links to omitted blocks and needs the complete flat block list.
    return list(walk(
        document, Visitor(default=lambda block, ctx: block, enter_section=_section_title),
        select=lambda block, ctx: not ctx.is_legacy_title,
    ))



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


def _safe_mathml(
    value: Any, *, aria_label: str = "", display: str = ""
) -> str | None:
    """Accept a bounded MathML tree without active markup, URLs or entities.

    ``aria_label`` (the formula's speech) and ``display`` (``"block"`` for a
    math block) are set on the ``<math>`` root itself, so the speech belongs to
    the MathML and is announced once while its tree stays navigable (#321).
    """
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
    nodes: list[Any] = []
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
    if aria_label:
        root.set("aria-label", aria_label)
    if display:
        root.set("display", display)
    return ElementTree.tostring(root, encoding="unicode")


def _allocate_id(base: str, reserved_ids: set[str] | None) -> str:
    """Returns ``base``, or ``base-2``, ``base-3``... when that ID is already taken, and reserves it.

    Args:
        base (str): Preferred (already escaped) element ID.
        reserved_ids (set|None): IDs already used in the page; updated in place. ``None`` skips the check.

    Returns:
        str: An ID not present in ``reserved_ids`` before the call.
    """
    if reserved_ids is None:
        return base
    candidate, suffix = base, 2
    while candidate in reserved_ids:
        candidate, suffix = f"{base}-{suffix}", suffix + 1
    reserved_ids.add(candidate)
    return candidate


def _visitor(
    profile: dict[str, Any],
    image_description: str,
    table_region: str,
    reserved_ids: set[str] | None,
    *,
    table_number: int = 0,
    toc: list[tuple[Any, Any, Any]] | None = None,
) -> Visitor[str]:
    def heading(block: dict[str, Any], ctx: BlockContext) -> str:
        if toc is not None:
            toc.append((
                block.get("level", 1),
                block.get("title", block.get("text", "")),
                block.get("id", ""),
            ))
        return _heading(block)

    def table(block: dict[str, Any], ctx: BlockContext) -> str:
        nonlocal table_number
        table_number += 1
        return _table(block, table_region, table_number, reserved_ids)

    return Visitor(
        default=lambda block, ctx: _text(block),
        heading=heading,
        paragraph=lambda block, ctx: _paragraph(block),
        list=lambda block, ctx: _list(block),
        table=table,
        image=lambda block, ctx: _image(block, image_description),
        code=lambda block, ctx: _code(block),
        math=lambda block, ctx: _math(block),
        quote=lambda block, ctx: _callout(block, reserved_ids),
        details=lambda block, ctx: _details(block, profile),
        note=lambda block, ctx: _callout(block, reserved_ids),
        warning=lambda block, ctx: _callout(block, reserved_ids),
    )


def _render_block(
    block: dict[str, Any],
    profile: dict[str, Any],
    image_description: str = "Image description",
    table_region: str = "Table {number}",
    table_number: int = 1,
    reserved_ids: set[str] | None = None,
) -> str:
    """Compatibility entry point for one block, using the document visitor."""
    return next(walk({"sections": [{"blocks": [block]}]}, _visitor(
        profile, image_description, table_region, reserved_ids,
        table_number=table_number - 1,
    )), "")


def _heading(block: dict[str, Any]) -> str:
    block_id = escape(block.get("id", ""))
    level = min(max(int(block.get("level", 1)), 1), 6)
    alias = block.get("title_alias", "")
    anchor = f'<span id="{escape(alias)}"></span>' if alias else ""
    return f'{anchor}<h{level} id="{block_id}">{escape(block.get("title", block.get("text", "")))}</h{level}>'


def _paragraph(block: dict[str, Any]) -> str:
    block_id = escape(block.get("id", ""))
    return f'<p id="{block_id}">{_prose_html(block.get("text", ""), block)}</p>'


def _code(block: dict[str, Any]) -> str:
    block_id = escape(block.get("id", ""))
    return (
        f'<pre id="{block_id}"><code>{escape(block.get("text", ""))}</code></pre>'
    )


def _list(block: dict[str, Any]) -> str:
    block_id = escape(block.get("id", ""))
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


def _table(block: dict[str, Any], table_region: str, table_number: int, reserved_ids: set[str] | None) -> str:
    block_id = escape(block.get("id", ""))
    table_ast = table_ast_from_block(block)
    if table_ast is None:
        return ""
    header_rows, body_rows, footer_rows = split_header_and_body(table_ast)

    caption = next((
        value.strip() for value in (
            table_ast.get("caption"), block.get("caption"), block.get("title"),
        ) if isinstance(value, str) and value.strip()
    ), "")
    caption_id = (
        _allocate_id(f"{block_id or f'table-{table_number}'}-caption", reserved_ids)
        if caption else ""
    )
    caption_html = (
        f'<caption id="{caption_id}">{_prose_html(caption, block)}</caption>'
        if caption
        else ""
    )
    region_name = (
        f'aria-labelledby="{caption_id}"'
        if caption
        else f'aria-label="{escape(table_region.format(number=table_number))}"'
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
        f'<div class="table-wrap" tabindex="0" role="region" {region_name}>'
        f'<table id="{block_id}">'
        f"{caption_html}{thead}{tbody}{tfoot}</table></div>"
    )


def _image(block: dict[str, Any], image_description: str) -> str:
    block_id = escape(block.get("id", ""))
    alt = escape(block.get("alt_text", block.get("text", "")))
    desc = escape(block.get("long_description", ""))
    details = (
        f"<details><summary>{escape(image_description)}</summary><p>{desc or alt}</p></details>"
        if desc
        else ""
    )
    return f'<figure id="{block_id}"><img alt="{alt}" src="{escape(block.get("metadata", {}).get("src", ""))}">{details}</figure>'


def _math(block: dict[str, Any]) -> str:
    block_id = escape(block.get("id", ""))
    metadata = block.get("metadata") or {}
    number = equation_number(metadata)
    speech = block.get("alt_text") or (block.get("text", "") if number else "")
    label = numbered_speech(str(speech), metadata)
    alt = escape(label)
    number_html = (
        f'<span class="equation-number" aria-hidden="true">({escape(number)})</span>'
        if number else ""
    )
    mathml = _safe_mathml(
        metadata.get("mathml", ""), aria_label=label, display="block"
    )
    if mathml:
        # A numbered equation is a row: the formula, its number on the right.
        css_class = ' class="equation"' if number_html else ""
        return f'<div id="{block_id}"{css_class}>{mathml}{number_html}</div>'
    return (
        f'<p id="{block_id}" role="math" aria-label="{alt}">'
        f'{escape(block.get("text", ""))}{number_html}</p>'
    )


def _callout(block: dict[str, Any], reserved_ids: set[str] | None) -> str:
    block_id = escape(block.get("id", ""))
    block_type = block.get("type")
    title = block.get("title")
    has_title = isinstance(title, str) and bool(title.strip())
    content = _prose_html(block.get("text", ""), block)
    if block_type == "quote":
        title_html = f"<p><strong>{escape(str(title))}</strong></p>" if has_title else ""
        return f'<blockquote id="{block_id}" class="quote">{title_html}<p>{content}</p></blockquote>'
    # role="note": several unnamed complementary landmarks inside <main>
    # would be indistinguishable; a callout is a note, not a landmark.
    title_html, name = "", ""
    if has_title:
        title_id = _allocate_id(f"{block_id or block_type}-title", reserved_ids)
        title_html = f'<p id="{title_id}"><strong>{escape(str(title))}</strong></p>'
        name = f' aria-labelledby="{title_id}"'
    return (
        f'<aside id="{block_id}" class="{block_type}" role="note"{name}>'
        f"{title_html}<p>{content}</p></aside>"
    )


def _details(block: dict[str, Any], profile: dict[str, Any]) -> str:
    block_id = escape(block.get("id", ""))
    block_type = block.get("type") or ""
    summary = escape(str(block.get("title") or block_type.title()))
    content = _prose_html(block.get("text", ""), block)
    if profile.get("collapsible"):
        return f'<details id="{block_id}"><summary>{summary}</summary><p>{content}</p></details>'
    return f'<section id="{block_id}"><h2>{summary}</h2><p>{content}</p></section>'


def _text(block: dict[str, Any]) -> str:
    block_id = escape(block.get("id", ""))
    # Retain the TypeError for unhashable kinds from the former set dispatch.
    hash(block.get("type"))
    return f'<p id="{block_id}">{escape(block.get("text", ""))}</p>'



def _prose_html(text: str, block: dict[str, Any]) -> str:
    """Escaped prose whose ``$…$`` spans are rendered as inline math.

    Each span is its MathML, labelled with its speech on the ``<math>`` element,
    as a math block is, when the enrichment produced it; else a
    ``role="math"`` span labelled with the speech around the (normalized)
    LaTeX without delimiters. A document that did not go through the canonical
    enrichment has no entries, and its spans keep the LaTeX, still marked as
    math.
    """
    entries = inline_math_entries(block)
    parts: list[str] = []
    for piece, is_math in split_inline_math(str(text)):
        if not is_math:
            parts.append(escape(piece))
            continue
        entry = entries.get(piece, {})
        speech = str(entry.get("speech") or "")
        mathml = _safe_mathml(entry.get("mathml", ""), aria_label=speech)
        if mathml:
            parts.append(mathml)
        else:
            label = f' aria-label="{escape(speech)}"' if speech else ""
            content = escape(str(entry.get("latex") or piece))
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

    toc: list[tuple[Any, Any, Any]] = []
    reserved_ids = {escape(str(block["id"])) for block in blocks if block.get("id")}
    reserved_ids |= {escape(str(block["title_alias"])) for block in blocks if block.get("title_alias")}
    body = list(walk({"sections": [{"blocks": blocks}]}, _visitor(
        profile_dict, labels.image_description,
        labels.extra.get("table_region", "Table {number}"), reserved_ids, toc=toc,
    )))

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
        "details,aside.note,aside.warning,blockquote.quote{background:#fff;border:1px solid #ddd;border-radius:10px;padding:.75rem 1rem;margin:1rem 0}",
        ".table-wrap{overflow-x:auto;margin:1rem 0}",
        "table{border-collapse:collapse;background:#fff}",
        "th,td{border:1px solid #999;padding:.35rem .75rem;text-align:left;vertical-align:top}",
        "th{background:#f3f4f6}",
        ".equation{display:flex;align-items:center}",
        ".equation>math{flex:1 1 auto}",
        ".equation-number{margin-left:1em;white-space:nowrap}",
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
