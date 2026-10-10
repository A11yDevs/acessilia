"""MinerU adapter: text extraction, line spacing, and de-hyphenation.

Pure: zero external dependencies, standard library only.
Parses MinerU `middle_json` output, preserves line breaks with single spaces,
reconstructs words split with trailing hyphens at line ends, and formats
formula and table blocks into canonical `.text`.
"""
from __future__ import annotations

from typing import Any

from docstruct.text.latex import wrap_latex


def clean_mineru_text(lines_or_pieces: list[str]) -> str:
    """Join line text pieces preserving spacing and de-hyphenating split words.

    - De-hyphenates words broken at end of line when followed by lowercase:
      e.g. ['impor-', 'tant'] -> 'important'
    - Preserves single spaces between distinct lines.
    """
    out = ""
    for item in lines_or_pieces:
        if not item:
            continue
        piece = str(item).strip()
        if not piece:
            continue

        if not out:
            out = piece
            continue

        # If previous piece ends with hyphen or soft hyphen and next piece begins with lowercase
        if out.endswith(("-", "\u00ad")) and piece[:1].islower():
            out = out[:-1] + piece
        else:
            if not out.endswith(" ") and not piece.startswith(" "):
                out += " " + piece
            else:
                out += piece

    return out


def format_mineru_block_text(block: dict[str, Any]) -> str:
    """Format a MinerU block's content into canonical text.

    - Formula blocks / spans: formatted with $...$ (inline) or $$...$$ (display).
    - Table blocks / spans: formatted with HTML representation.
    - Text blocks: lines joined with clean spacing and de-hyphenation.
    """
    block_type = str(block.get("type", "")).lower()

    # 1. Table formatting
    if block_type == "table":
        # Check sub-blocks for table_body
        for sub in block.get("blocks", []) or []:
            if sub.get("type") == "table_body":
                for line in sub.get("lines", []) or []:
                    for span in line.get("spans", []) or []:
                        if span.get("type") == "table" and span.get("html"):
                            return str(span["html"]).strip()
        # Direct span fallback
        for line in block.get("lines", []) or []:
            for span in line.get("spans", []) or []:
                if span.get("type") == "table" and span.get("html"):
                    return str(span["html"]).strip()
        if block.get("html"):
            return str(block["html"]).strip()

    # 2. Standalone formula formatting
    if block_type in ("interline_equation", "equation"):
        latex = block.get("latex")
        if not latex:
            # Check lines/spans
            for line in block.get("lines", []) or []:
                for span in line.get("spans", []) or []:
                    content = span.get("content") or span.get("latex")
                    if content:
                        latex = str(content)
                        break
        if latex:
            return wrap_latex(str(latex), display=True)

    # 3. Line-based text extraction with inline formula/table handling
    lines = block.get("lines") or []
    if lines:
        line_texts: list[str] = []
        for line in lines:
            line_parts: list[str] = []
            for span in line.get("spans", []) or []:
                span_type = str(span.get("type", "")).lower()
                content = span.get("content") or span.get("text") or span.get("latex")
                if content is None:
                    continue
                content_str = str(content)

                if span_type == "inline_equation":
                    line_parts.append(wrap_latex(content_str, display=False))
                elif span_type in ("interline_equation", "equation"):
                    line_parts.append(wrap_latex(content_str, display=True))
                elif span_type == "table" and span.get("html"):
                    line_parts.append(str(span["html"]).strip())
                else:
                    line_parts.append(content_str)

            if line_parts:
                line_str = "".join(line_parts).strip()
                if line_str:
                    line_texts.append(line_str)

        if line_texts:
            return clean_mineru_text(line_texts)

    # 4. Fallback to existing text attribute
    raw_text = block.get("text")
    if raw_text:
        return str(raw_text).strip()

    return ""


def extract_mineru_blocks(
    middle_json: dict[str, Any] | list[dict[str, Any]],
    *,
    include_discarded: bool = False,
) -> list[dict[str, Any]]:
    """Extract and sanitize blocks from MinerU middle_json into canonical block dictionaries.

    Args:
        middle_json: MinerU output dictionary containing 'pdf_info', or list of page dicts.
        include_discarded: Whether to include blocks from 'discarded_blocks'.

    Returns:
        List of block dicts with 'type', 'bbox', 'text', 'page_index', and 'metadata'.
    """
    if isinstance(middle_json, list):
        pages = middle_json
    elif isinstance(middle_json, dict):
        pages = middle_json.get("pdf_info") or []
    else:
        return []

    extracted: list[dict[str, Any]] = []

    for page in pages:
        if not isinstance(page, dict):
            continue
        page_idx = int(page.get("page_idx", 0))
        page_size = page.get("page_size")

        sources: list[tuple[dict[str, Any], bool]] = [
            (b, False) for b in (page.get("preproc_blocks") or []) if isinstance(b, dict)
        ]
        if include_discarded:
            sources.extend(
                (b, True) for b in (page.get("discarded_blocks") or []) if isinstance(b, dict)
            )

        for block, is_discarded in sources:
            block_type = str(block.get("type", "unknown"))
            raw_bbox = block.get("bbox")
            bbox = None
            if isinstance(raw_bbox, (list, tuple)) and len(raw_bbox) == 4:
                bbox = (
                    float(raw_bbox[0]),
                    float(raw_bbox[1]),
                    float(raw_bbox[2]),
                    float(raw_bbox[3]),
                )

            text = format_mineru_block_text(block)

            extracted.append({
                "type": block_type,
                "text": text,
                "bbox": bbox,
                "page_index": page_idx,
                "metadata": {
                    "page_size": page_size,
                    "discarded": is_discarded,
                    "raw_type": block.get("type"),
                },
            })

    return extracted
