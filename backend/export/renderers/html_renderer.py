from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Any

from backend.export.filters.pandoc_filters import apply_output_profile_filter
from backend.pipeline.table_ast import split_header_and_body
from backend.pipeline.table_ast import table_ast_from_block
from backend.pipeline.verbosity_manager import normalize_profile


def render_html(
    document: dict[str, Any], output_path: Path, profile_name: str = "html"
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    profile = normalize_profile(profile_name)
    blocks = apply_output_profile_filter(_all_blocks(document), profile_name)

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
        body.append(_render_block(block, profile))

    html = [
        "<!doctype html>",
        f'<html lang="{escape(document.get("language", "pt-BR"))}">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>{escape(document.get('title', 'Documento acessível'))}</title>",
        "<style>",
        "body{font-family:system-ui,-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;line-height:1.6;max-width:980px;margin:0 auto;padding:2rem;background:#fafafa;color:#1c1c1c}",
        "nav.toc{background:#fff;border:1px solid #ddd;border-radius:12px;padding:1rem 1.25rem;margin-bottom:1.5rem}",
        "nav.toc ul{margin:0;padding-left:1.2rem}",
        "pre{overflow:auto;background:#111;color:#f4f4f4;padding:1rem;border-radius:10px}",
        "code{font-family:ui-monospace,SFMono-Regular,Consolas,monospace}",
        "details{background:#fff;border:1px solid #ddd;border-radius:10px;padding:.75rem 1rem;margin:1rem 0}",
        "aside.meta{background:#f3f4f6;border-left:4px solid #7c3aed;padding:.75rem 1rem;margin:1.5rem 0}",
        "</style>",
        "</head>",
        "<body>",
        f'<main aria-label="{escape(document.get("title", "Documento acessível"))}">',
    ]
    if toc:
        html.append(
            '<nav class="toc" aria-label="Sumário"><strong>Sumário</strong><ul>'
        )
        for level, title, link_id in toc:
            html.append(
                f'<li class="lvl-{level}"><a href="#{escape(link_id)}">{escape(title)}</a></li>'
            )
        html.append("</ul></nav>")
    html.extend(body)
    if profile.get("interactive"):
        html.append(
            '<aside class="meta"><h2>Metadados técnicos</h2><p>'
            + escape(str(document.get("metadata", {})))
            + "</p></aside>"
        )
    html.append("</main></body></html>")
    output_path.write_text("\n".join(html), encoding="utf-8")
    return output_path


def _all_blocks(document: dict[str, Any]) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for section in document.get("sections", []):
        blocks.extend(_collect_section(section))
    return blocks


def _collect_section(section: dict[str, Any]) -> list[dict[str, Any]]:
    blocks = (
        [
            {
                "type": "heading",
                "level": section.get("level", 1),
                "title": section.get("title", ""),
                "id": section.get("id", ""),
            }
        ]
        if section.get("title")
        else []
    )
    blocks.extend(section.get("blocks", []))
    for child in section.get("children", []):
        blocks.extend(_collect_section(child))
    return blocks


def _render_block(block: dict[str, Any], profile: dict[str, Any]) -> str:
    block_type = block.get("type")
    block_id = escape(block.get("id", ""))
    if block_type == "heading":
        level = min(max(int(block.get("level", 1)), 1), 6)
        return f'<h{level} id="{block_id}">{escape(block.get("title", block.get("text", "")))}</h{level}>'
    if block_type == "paragraph":
        return f'<p id="{block_id}">{escape(block.get("text", ""))}</p>'
    if block_type == "code":
        return (
            f'<pre id="{block_id}"><code>{escape(block.get("text", ""))}</code></pre>'
        )
    if block_type == "list":
        tag = "ol" if block.get("ordered") else "ul"
        items = "".join(
            f"<li>{escape(str(item))}</li>" for item in block.get("items", [])
        )
        return f'<{tag} id="{block_id}">{items}</{tag}>'
    if block_type == "table":
        table_ast = table_ast_from_block(block)
        if table_ast is None:
            return ""
        header_rows, body_rows, footer_rows = split_header_and_body(table_ast)

        caption = table_ast.get("caption")
        caption_html = (
            f"<caption>{escape(str(caption))}</caption>"
            if isinstance(caption, str) and caption.strip()
            else ""
        )

        thead = ""
        if header_rows:
            thead_rows = "".join(_render_html_table_row(row, header=True) for row in header_rows)
            thead = f"<thead>{thead_rows}</thead>"

        tbody_rows = "".join(_render_html_table_row(row, header=False) for row in body_rows)
        tbody = f"<tbody>{tbody_rows}</tbody>" if tbody_rows else ""

        tfoot = ""
        if footer_rows:
            tfoot_rows = "".join(_render_html_table_row(row, header=False) for row in footer_rows)
            tfoot = f"<tfoot>{tfoot_rows}</tfoot>"

        return f'<table id="{block_id}">{caption_html}{thead}{tbody}{tfoot}</table>'
    if block_type == "image":
        alt = escape(block.get("alt_text", block.get("text", "")))
        desc = escape(block.get("long_description", ""))
        details = (
            f"<details><summary>Descrição da imagem</summary><p>{desc or alt}</p></details>"
            if desc
            else ""
        )
        return f'<figure id="{block_id}"><img alt="{alt}" src="{escape(block.get("metadata", {}).get("src", ""))}">{details}</figure>'
    if block_type == "math":
        return f'<p id="{block_id}"><math>{escape(block.get("text", ""))}</math></p>'
    if block_type in {"details", "note", "warning", "quote"}:
        summary = escape(block.get("title", block_type.title()))
        content = escape(block.get("text", ""))
        if profile.get("collapsible"):
            return f'<details id="{block_id}"><summary>{summary}</summary><p>{content}</p></details>'
        return f'<section id="{block_id}"><h2>{summary}</h2><p>{content}</p></section>'
    return f'<p id="{block_id}">{escape(block.get("text", ""))}</p>'


def _render_html_table_row(row: dict[str, Any], *, header: bool) -> str:
    cells = row.get("cells", []) if isinstance(row, dict) else []
    tag = "th" if header else "td"
    rendered_cells: list[str] = []
    for cell in cells:
        if not isinstance(cell, dict):
            continue
        text = escape(str(cell.get("text", "")).strip())
        if not text:
            continue

        attrs: list[str] = []
        if tag == "th":
            scope = cell.get("scope")
            if isinstance(scope, str) and scope in {"row", "col", "rowgroup", "colgroup"}:
                attrs.append(f'scope="{scope}"')
            else:
                attrs.append('scope="col"')

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
