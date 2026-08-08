from __future__ import annotations

import re


def extract_plain_heading(line: str, current_blocks: int) -> tuple[int, str] | None:
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
        return level, prefixed.group(1).strip()

    numbered = re.match(r"^(\d+(?:\.\d+){0,2})\s+(.+)$", line)
    if numbered and len(line) <= 120:
        depth = numbered.group(1).count(".")
        return min(4, depth + 2), line.strip()

    if looks_like_upper_heading(line):
        return (1 if current_blocks == 0 else 2), line.strip()

    return None


def looks_like_upper_heading(line: str) -> bool:
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


def starts_with_list_marker(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    if re.match(r"^(?:[-*+]|•|‣|⁃|→|⇒)\s+", stripped):
        return True
    if re.match(r"^\(?\d+\)|^\d+\)\s+", stripped):
        return True
    if re.match(r"^\d+\.\s+", stripped):
        return True
    return False


def classify_text_block(
    *,
    text: str,
    current_blocks: int,
    avg_font_size: float,
    median_font_size: float,
    line_count: int,
    is_bold: bool,
    is_monospace: bool,
) -> tuple[str, int]:
    cleaned = text.strip()
    if not cleaned:
        return "paragraph", 1

    plain_heading = extract_plain_heading(cleaned, current_blocks)
    if plain_heading is not None:
        level, _ = plain_heading
        return "heading", level

    # Indício forte de heading tipográfico.
    if (
        cleaned
        and len(cleaned) <= 120
        and line_count <= 3
        and avg_font_size >= (median_font_size + 1.0)
        and (is_bold or looks_like_upper_heading(cleaned))
    ):
        return "heading", 2 if current_blocks > 0 else 1

    if is_monospace and "\n" in cleaned:
        return "code", 1

    if starts_with_list_marker(cleaned):
        return "list_item", 1

    return "paragraph", 1
