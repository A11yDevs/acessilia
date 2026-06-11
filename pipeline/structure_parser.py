from __future__ import annotations

import re
from typing import Any
from uuid import uuid4

from pipeline.sanitizer import sanitize_block_text


def parse_text_to_blocks(text: str) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if not stripped:
            i += 1
            continue
        heading_match = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if heading_match:
            blocks.append(
                {
                    "type": "heading",
                    "level": len(heading_match.group(1)),
                    "text": sanitize_block_text(
                        heading_match.group(2).strip()
                    ),
                }
            )
            i += 1
            continue
        plain_heading = _extract_plain_heading(stripped, len(blocks))
        if plain_heading is not None:
            blocks.append(plain_heading)
            i += 1
            continue
        marker_block = _try_parse_marker_block(lines, i)
        if marker_block is not None:
            block, consumed = marker_block
            blocks.append(block)
            i = consumed
            continue
        if re.match(r"^(?:[-*+]\s+)", stripped):
            blocks.append(
                {
                    "type": "list",
                    "ordered": False,
                    "items": [sanitize_block_text(stripped[2:].strip())],
                }
            )
            i += 1
            continue
        if re.match(r"^(?:\(?\d+\)|\d+\))\s+", stripped):
            blocks.append(
                {
                    "type": "list",
                    "ordered": True,
                    "items": [
                        sanitize_block_text(
                            re.sub(r"^(?:\(?\d+\)|\d+\))\s+", "", stripped),
                        )
                    ],
                }
            )
            i += 1
            continue
        if re.match(r"^\d+\.\s+", stripped):
            blocks.append(
                {
                    "type": "list",
                    "ordered": True,
                    "items": [
                        sanitize_block_text(
                            re.sub(r"^\d+\.\s+", "", stripped),
                        )
                    ],
                }
            )
            i += 1
            continue
        if stripped.startswith("```"):
            blocks.append({"type": "code", "text": stripped})
            i += 1
            continue
        if _looks_like_table_row(stripped):
            rows, end_index = _parse_table_rows(lines, i)
            if rows:
                blocks.append({"type": "table", "rows": rows})
                i = end_index + 1
                continue
        blocks.append(
            {
                "type": "paragraph",
                "text": sanitize_block_text(stripped),
            }
        )
        i += 1
    return _attach_ids(blocks)


def _attach_ids(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for index, block in enumerate(blocks, start=1):
        block.setdefault("id", f"blk-{uuid4().hex[:10]}-{index}")
    return blocks


def _looks_like_table_row(line: str) -> bool:
    return line.startswith("|") and line.endswith("|")


def _extract_plain_heading(
    line: str,
    current_blocks: int,
) -> dict[str, Any] | None:
    prefixed = re.match(
        (
            r"^(?:titulo|t[ií]tulo|secao|se[cç][aã]o|"
            r"capitulo|cap[ií]tulo(?:\s+\d+)?)\s*:\s*(.+)$"
        ),
        line,
        re.IGNORECASE,
    )
    if prefixed:
        keyword = line.split(":", 1)[0].strip().lower()
        level = 1 if "titulo" in keyword or "título" in keyword else 2
        return {
            "type": "heading",
            "level": level,
            "text": sanitize_block_text(prefixed.group(1).strip()),
        }

    if _looks_like_upper_heading(line):
        level = 1 if current_blocks == 0 else 2
        return {
            "type": "heading",
            "level": level,
            "text": sanitize_block_text(line),
        }
    return None


def _try_parse_marker_block(
    lines: list[str],
    i: int,
) -> tuple[dict[str, Any], int] | None:
    stripped = lines[i].strip()
    m = re.match(r"^In[íi]cio de (.+):$", stripped, re.IGNORECASE)
    if not m:
        return None

    type_name = m.group(1).strip()
    end_marker = f"Fim de {type_name}"

    content_lines: list[str] = []
    j = i + 1
    while j < len(lines):
        if lines[j].strip() == end_marker:
            j += 1
            break
        content_lines.append(lines[j])
        j += 1

    type_key = type_name.lower().replace(" ", "-")

    if type_key in ("lista",):
        items = []
        for cl in content_lines:
            cl_stripped = cl.strip()
            if cl_stripped:
                item_text = re.sub(r"^[-*+]\s+", "", cl_stripped).strip()
                items.append(sanitize_block_text(item_text))
        return {"type": "list", "ordered": False, "items": items}, j

    if type_key in ("código-fonte", "codigo-fonte"):
        code_text = "\n".join(cl.rstrip("\n") for cl in content_lines).strip()
        return {"type": "code", "text": code_text}, j

    if type_key == "imagem":
        text = sanitize_block_text(
            "\n".join(cl.strip() for cl in content_lines if cl.strip())
        )
        return {"type": "image", "text": text}, j

    callout_types = {
        "nota", "citação", "citacao", "barra lateral",
        "aviso", "dica", "importante", "box",
    }
    if type_key in callout_types:
        text = sanitize_block_text(
            "\n".join(cl.strip() for cl in content_lines if cl.strip())
        )
        return {"type": "callout", "text": text, "callout_type": type_name}, j

    return None


def _looks_like_upper_heading(line: str) -> bool:
    has_letter = any(ch.isalpha() for ch in line)
    if not has_letter:
        return False
    if len(line) > 90:
        return False
    if line.endswith((".", ";", "!", "?")):
        return False
    if ":" in line:
        return False
    return line == line.upper()


def _parse_table_rows(
    lines: list[str],
    start_index: int,
) -> tuple[list[list[str]], int]:
    rows: list[list[str]] = []
    i = start_index

    while i < len(lines):
        stripped = lines[i].strip()
        if not _looks_like_table_row(stripped):
            break
        cells = [
            sanitize_block_text(cell.strip())
            for cell in stripped.strip("|").split("|")
        ]
        if cells and all(set(cell) <= {"-", ":"} for cell in cells):
            i += 1
            continue
        rows.append(cells)
        i += 1

    return rows, i - 1
