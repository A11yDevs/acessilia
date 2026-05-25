from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Any

from filters.pandoc_filters import apply_output_profile_filter
from pipeline.verbosity_manager import normalize_profile


def render_html(document: dict[str, Any], output_path: Path, profile_name: str = "html") -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    profile = normalize_profile(profile_name)
    blocks = apply_output_profile_filter(_all_blocks(document), profile_name)

    toc = []
    body = []
    for block in blocks:
        if block.get("type") == "heading":
            toc.append((block.get("level", 1), block.get("title", block.get("text", "")), block.get("id", "")))
        body.append(_render_block(block, profile))

    html = ["<!doctype html>", f'<html lang="{escape(document.get("language", "pt-BR"))}">', "<head>", '<meta charset="utf-8">', '<meta name="viewport" content="width=device-width, initial-scale=1">', f"<title>{escape(document.get('title', 'Documento acessível'))}</title>", "<style>", "body{font-family:system-ui,-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;line-height:1.6;max-width:980px;margin:0 auto;padding:2rem;background:#fafafa;color:#1c1c1c}", "nav.toc{background:#fff;border:1px solid #ddd;border-radius:12px;padding:1rem 1.25rem;margin-bottom:1.5rem}", "nav.toc ul{margin:0;padding-left:1.2rem}", "pre{overflow:auto;background:#111;color:#f4f4f4;padding:1rem;border-radius:10px}", "code{font-family:ui-monospace,SFMono-Regular,Consolas,monospace}", "details{background:#fff;border:1px solid #ddd;border-radius:10px;padding:.75rem 1rem;margin:1rem 0}", "aside.meta{background:#f3f4f6;border-left:4px solid #7c3aed;padding:.75rem 1rem;margin:1.5rem 0}", "</style>", "</head>", "<body>", f'<main aria-label="{escape(document.get("title", "Documento acessível"))}">', f'<h1 id="{escape(document.get("sections", [{}])[0].get("id", "documento"))}">{escape(document.get("title", "Documento acessível"))}</h1>']
    if toc:
        html.append('<nav class="toc" aria-label="Sumário"><strong>Sumário</strong><ul>')
        for level, title, link_id in toc:
            html.append(f'<li class="lvl-{level}"><a href="#{escape(link_id)}">{escape(title)}</a></li>')
        html.append("</ul></nav>")
    html.extend(body)
    if profile.get("interactive"):
        html.append('<aside class="meta"><h2>Metadados técnicos</h2><p>' + escape(str(document.get("metadata", {}))) + "</p></aside>")
    html.append("</main></body></html>")
    output_path.write_text("\n".join(html), encoding="utf-8")
    return output_path


def _all_blocks(document: dict[str, Any]) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for section in document.get("sections", []):
        blocks.extend(_collect_section(section))
    return blocks


def _collect_section(section: dict[str, Any]) -> list[dict[str, Any]]:
    blocks = [{"type": "heading", "level": section.get("level", 1), "title": section.get("title", ""), "id": section.get("id", "")}] if section.get("title") else []
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
        return f'<pre id="{block_id}"><code>{escape(block.get("text", ""))}</code></pre>'
    if block_type == "list":
        tag = "ol" if block.get("ordered") else "ul"
        items = "".join(f"<li>{escape(str(item))}</li>" for item in block.get("items", []))
        return f'<{tag} id="{block_id}">{items}</{tag}>'
    if block_type == "table":
        rows = block.get("rows", [])
        if not rows:
            return ""
        header = rows[0]
        body_rows = rows[1:] or []
        thead = "<tr>" + "".join(f"<th>{escape(str(cell))}</th>" for cell in header) + "</tr>"
        tbody = "".join("<tr>" + "".join(f"<td>{escape(str(cell))}</td>" for cell in row) + "</tr>" for row in body_rows)
        return f'<table id="{block_id}"><thead>{thead}</thead><tbody>{tbody}</tbody></table>'
    if block_type == "image":
        alt = escape(block.get("alt_text", block.get("text", "")))
        desc = escape(block.get("long_description", ""))
        details = f'<details><summary>Descrição da imagem</summary><p>{desc or alt}</p></details>' if desc else ""
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